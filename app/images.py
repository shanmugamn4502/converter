"""Image tools: compress, resize, crop/rotate, remove location data, favicon."""

import io
import json
import zipfile

from PIL import Image, ImageOps

from .convert import ConversionError, InputFile, OutputFile, open_image, prepare, stem

# Pillow format -> (our key, extension, mime). Anything else is saved as JPG.
KEEPABLE = {
    "JPEG": ("jpg", "jpg", "image/jpeg"),
    "PNG": ("png", "png", "image/png"),
    "WEBP": ("webp", "webp", "image/webp"),
}
JPG = KEEPABLE["JPEG"]


def detect(f: InputFile) -> tuple[Image.Image, tuple[str, str, str]]:
    """Open the image and decide which format the result is saved in."""
    img = open_image(f)
    with Image.open(io.BytesIO(f.data)) as raw:
        fmt = raw.format
    return img, KEEPABLE.get(fmt, JPG)


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)


def encode(img: Image.Image, key: str, quality: int = 90, icc: bytes | None = None) -> bytes:
    out = io.BytesIO()
    extra = {"icc_profile": icc} if icc else {}
    if key == "jpg":
        prepare(img, "JPEG").save(out, "JPEG", quality=quality, optimize=True, progressive=True, **extra)
    elif key == "webp":
        img = img if img.mode in ("RGB", "RGBA") else img.convert("RGBA" if has_alpha(img) else "RGB")
        img.save(out, "WEBP", quality=quality, method=5, **extra)
    else:
        img.save(out, "PNG", optimize=True, **extra)
    return out.getvalue()


def shrink_to(img: Image.Image, long_edge: int) -> Image.Image:
    if max(img.size) <= long_edge:
        return img
    img = img.copy()
    img.thumbnail((long_edge, long_edge), Image.LANCZOS)
    return img


# ---------------------------------------------------------------- compress

LEVELS = {  # level -> (jpg/webp quality, longest edge in px, png colours)
    "light": (85, 4000, None),
    "balanced": (72, 2560, 256),
    "strong": (55, 1600, 128),
}


def fit_under(img: Image.Image, key: str, limit: int) -> bytes:
    """Highest quality that fits under `limit` bytes; shrink the image if even
    low quality is too big."""
    for _ in range(8):
        lo, hi, best = 25, 95, None
        while lo <= hi:
            q = (lo + hi) // 2
            data = encode(img, key, q)
            if len(data) <= limit:
                best, lo = data, q + 1
            else:
                hi = q - 1
        if best:
            return best
        img = img.resize((max(1, int(img.width * 0.8)), max(1, int(img.height * 0.8))), Image.LANCZOS)
    raise ConversionError(f"Couldn't get the image under {limit // 1024} KB.")


def compress_image(f: InputFile, level: str, target_kb: int | None) -> OutputFile:
    img, (key, ext, mime) = detect(f)

    if target_kb:
        if key == "png":  # PNG has no quality dial; switch to a format that does
            key, ext, mime = ("webp", "webp", "image/webp") if has_alpha(img) else JPG
        data = fit_under(img, key, target_kb * 1024)
    else:
        quality, edge, colours = LEVELS.get(level, LEVELS["balanced"])
        img = shrink_to(img, edge)
        if key == "png" and colours:
            img = img.quantize(colors=colours, method=Image.FASTOCTREE if has_alpha(img) else Image.MEDIANCUT)
        data = encode(img, key, quality)

    if len(data) >= len(f.data) and ext == f.name.rsplit(".", 1)[-1].lower():
        data = f.data  # never hand back a bigger file than they gave us
    return OutputFile(f"{stem(f.name)}-compressed.{ext}", data, mime)


# ---------------------------------------------------------------- resize

def resize_image(f: InputFile, width: int | None, height: int | None, percent: int | None, fit: str) -> OutputFile:
    img, (key, ext, mime) = detect(f)
    w, h = img.size

    if percent:
        size = (max(1, round(w * percent / 100)), max(1, round(h * percent / 100)))
        img = img.resize(size, Image.LANCZOS)
    elif width and height:
        if fit == "cover":  # fill the box exactly, trimming the edges
            img = ImageOps.fit(img, (width, height), Image.LANCZOS)
        elif fit == "stretch":
            img = img.resize((width, height), Image.LANCZOS)
        else:  # contain: fit inside the box, keep the whole picture
            img = ImageOps.contain(img, (width, height), Image.LANCZOS)
    elif width:
        img = img.resize((width, max(1, round(h * width / w))), Image.LANCZOS)
    elif height:
        img = img.resize((max(1, round(w * height / h)), height), Image.LANCZOS)
    else:
        raise ConversionError("Enter a width, a height or a percentage.")

    if max(img.size) > 10000:
        raise ConversionError("That's too large. Keep both sides under 10,000 pixels.")
    return OutputFile(f"{stem(f.name)}-{img.width}x{img.height}.{ext}", encode(img, key, 92), mime)


# ---------------------------------------------------------------- crop & rotate

RATIOS = {"1:1": (1, 1), "4:5": (4, 5), "3:4": (3, 4), "4:3": (4, 3), "16:9": (16, 9), "9:16": (9, 16)}


def crop_rotate(f: InputFile, rotate: int, flip: str, ratio: str) -> OutputFile:
    img, (key, ext, mime) = detect(f)

    if rotate in (90, 180, 270):
        img = img.rotate(-rotate, expand=True)  # Pillow turns anti-clockwise
    if flip == "horizontal":
        img = ImageOps.mirror(img)
    elif flip == "vertical":
        img = ImageOps.flip(img)

    if ratio in RATIOS:
        rw, rh = RATIOS[ratio]
        w, h = img.size
        if w / h > rw / rh:
            nw = round(h * rw / rh)
            img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = round(w * rh / rw)
            img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))

    return OutputFile(f"{stem(f.name)}-edited.{ext}", encode(img, key, 92), mime)


# ---------------------------------------------------------------- remove location / camera data

GPS, MAKE, MODEL, DATETIME, DATETIME_ORIGINAL, SOFTWARE = 34853, 271, 272, 306, 36867, 305


def found_metadata(f: InputFile) -> list[str]:
    try:
        with Image.open(io.BytesIO(f.data)) as raw:
            exif = raw.getexif()
            sub = exif.get_ifd(0x8769)
    except Exception:
        return []
    found = []
    if exif.get_ifd(GPS) or GPS in exif:
        found.append("location")
    if MAKE in exif or MODEL in exif:
        found.append("camera model")
    if DATETIME in exif or DATETIME_ORIGINAL in sub:
        found.append("date taken")
    if SOFTWARE in exif:
        found.append("editing software")
    return found


def strip_metadata(f: InputFile) -> tuple[OutputFile, list[str]]:
    found = found_metadata(f)
    img, (key, ext, mime) = detect(f)  # detect() already turns the photo upright
    icc = img.info.get("icc_profile")  # keep colour profile so colours don't shift
    # Rebuild from raw pixels so no metadata can ride along.
    clean = Image.frombytes(img.mode, img.size, img.tobytes())
    if img.mode == "P":
        clean.putpalette(img.getpalette())
        if "transparency" in img.info:
            clean.info["transparency"] = img.info["transparency"]
    return OutputFile(f"{stem(f.name)}-clean.{ext}", encode(clean, key, 95, icc), mime), found


# ---------------------------------------------------------------- favicon

def make_favicon(f: InputFile) -> OutputFile:
    img = open_image(f).convert("RGBA")
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))  # pad, never crop a logo
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))

    def png(px: int) -> bytes:
        out = io.BytesIO()
        square.resize((px, px), Image.LANCZOS).save(out, "PNG", optimize=True)
        return out.getvalue()

    ico = io.BytesIO()
    square.save(ico, "ICO", sizes=[(16, 16), (32, 32), (48, 48)])

    manifest = {
        "name": "", "short_name": "",
        "icons": [
            {"src": "/android-chrome-192x192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/android-chrome-512x512.png", "sizes": "512x512", "type": "image/png"},
        ],
        "theme_color": "#ffffff", "background_color": "#ffffff", "display": "standalone",
    }
    snippet = (
        '<link rel="icon" href="/favicon.ico" sizes="48x48">\n'
        '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32x32.png">\n'
        '<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16x16.png">\n'
        '<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">\n'
        '<link rel="manifest" href="/site.webmanifest">\n'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("favicon.ico", ico.getvalue())
        z.writestr("favicon-16x16.png", png(16))
        z.writestr("favicon-32x32.png", png(32))
        z.writestr("apple-touch-icon.png", png(180))
        z.writestr("android-chrome-192x192.png", png(192))
        z.writestr("android-chrome-512x512.png", png(512))
        z.writestr("site.webmanifest", json.dumps(manifest, indent=2))
        z.writestr("paste-into-head.html", snippet)
    return OutputFile("favicon.zip", buf.getvalue(), "application/zip")
