"""Pure conversion logic — no web code here, so it is easy to test."""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

import pymupdf
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # lets Pillow open iPhone .heic photos

# Refuse absurdly large images instead of exhausting the server's ~900 MB RAM.
Image.MAX_IMAGE_PIXELS = 60_000_000

MAX_PDF_PAGES = 50

# target -> (Pillow format name, file extension, mime type)
IMAGE_TARGETS = {
    "png": ("PNG", "png", "image/png"),
    "jpg": ("JPEG", "jpg", "image/jpeg"),
    "webp": ("WEBP", "webp", "image/webp"),
    "gif": ("GIF", "gif", "image/gif"),
    "bmp": ("BMP", "bmp", "image/bmp"),
    "tiff": ("TIFF", "tiff", "image/tiff"),
    "ico": ("ICO", "ico", "image/x-icon"),
}
TARGETS = set(IMAGE_TARGETS) | {"pdf"}

# Formats that cannot store transparency: flatten onto white.
NO_ALPHA = {"JPEG", "BMP", "PDF"}


class ConversionError(ValueError):
    """A problem the user can fix (wrong file, unsupported choice)."""


@dataclass
class InputFile:
    name: str
    data: bytes


@dataclass
class OutputFile:
    name: str
    data: bytes
    mime: str


def is_pdf(f: InputFile) -> bool:
    return f.data[:5] == b"%PDF-"


def stem(name: str) -> str:
    return PurePath(name).stem or "file"


def open_image(f: InputFile) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(f.data))
        img.load()
    except Image.DecompressionBombError:
        raise ConversionError(f"{f.name} is too large to convert (over 60 megapixels).")
    except Exception:
        raise ConversionError(f"{f.name} isn't an image or PDF this tool can read.")
    return ImageOps.exif_transpose(img)  # keep phone photos the right way up


def prepare(img: Image.Image, pil_format: str) -> Image.Image:
    if pil_format in NO_ALPHA:
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            bg = Image.new("RGB", rgba.size, "white")
            bg.paste(rgba, mask=rgba.getchannel("A"))
            return bg
        return img.convert("RGB") if img.mode != "RGB" else img
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        return img.convert("RGBA")
    return img


def save_image(img: Image.Image, target: str, quality: int) -> bytes:
    pil_format = IMAGE_TARGETS[target][0]
    img = prepare(img, pil_format)
    out = io.BytesIO()
    if pil_format == "JPEG":
        img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    elif pil_format == "WEBP":
        img.save(out, "WEBP", quality=quality, method=4)
    elif pil_format == "ICO":
        img.save(out, "ICO", sizes=[(s, s) for s in (16, 32, 48, 64, 128, 256)])
    else:
        img.save(out, pil_format)
    return out.getvalue()


def render_pdf(f: InputFile, target: str, dpi: int, quality: int) -> list[OutputFile]:
    try:
        doc = pymupdf.open(stream=f.data, filetype="pdf")
    except Exception:
        raise ConversionError(f"{f.name} looks like a PDF but can't be opened.")
    if doc.needs_pass:
        raise ConversionError(f"{f.name} is password-protected. Remove the password and try again.")
    if doc.page_count > MAX_PDF_PAGES:
        raise ConversionError(f"{f.name} has {doc.page_count} pages. The limit is {MAX_PDF_PAGES}.")

    ext, mime = IMAGE_TARGETS[target][1:]
    outputs = []
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        suffix = f"-page-{i}" if doc.page_count > 1 else ""
        outputs.append(OutputFile(f"{stem(f.name)}{suffix}.{ext}", save_image(img, target, quality), mime))
    doc.close()
    return outputs


def images_to_pdf(files: list[InputFile], dpi: int) -> OutputFile:
    pages = [prepare(open_image(f), "PDF") for f in files]
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    name = f"{stem(files[0].name)}.pdf" if len(files) == 1 else "combined.pdf"
    return OutputFile(name, out.getvalue(), "application/pdf")


def convert(files: list[InputFile], target: str, quality: int = 90, dpi: int = 150) -> list[OutputFile]:
    if not files:
        raise ConversionError("Add at least one file.")
    if target not in TARGETS:
        raise ConversionError(f"Can't convert to {target}.")

    if target == "pdf":
        if any(is_pdf(f) for f in files):
            raise ConversionError("Those are already PDFs. Choose an image format instead.")
        return [images_to_pdf(files, dpi)]

    outputs = []
    for f in files:
        if is_pdf(f):
            outputs += render_pdf(f, target, dpi, quality)
        else:
            ext, mime = IMAGE_TARGETS[target][1:]
            outputs.append(OutputFile(f"{stem(f.name)}.{ext}", save_image(open_image(f), target, quality), mime))
    return outputs


def bundle(outputs: list[OutputFile]) -> OutputFile:
    """One result goes back as-is; several go back as a single zip."""
    if len(outputs) == 1:
        return outputs[0]
    buf = io.BytesIO()
    seen: dict[str, int] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for o in outputs:
            name = o.name
            if name in seen:  # two inputs called photo.png -> photo.jpg, photo-2.jpg
                seen[name] += 1
                p = PurePath(name)
                name = f"{p.stem}-{seen[o.name]}{p.suffix}"
            else:
                seen[name] = 1
            z.writestr(name, o.data)
    return OutputFile("converted.zip", buf.getvalue(), "application/zip")
