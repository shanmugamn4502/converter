"""Tools that call outside programs: Tesseract (OCR), ffmpeg (video), LibreOffice (Word -> PDF).

Each runs in its own temp folder that is deleted afterwards. Programs are
called with argument lists, never through a shell, and user file names are
never used on disk.
"""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePath

import pymupdf
import pytesseract
from PIL import Image

from .convert import ConversionError, InputFile, OutputFile, is_pdf, open_image, stem

OCR_LANGS = {"eng", "tam", "hin", "eng+tam", "eng+hin"}
OCR_MAX_PAGES = 20
VIDEO_MAX_SECONDS = 10 * 60
GIF_MAX_SECONDS = 15


def require(program: str, purpose: str):
    if not shutil.which(program):
        raise ConversionError(f"{purpose} isn't available on this server right now.")


def run(args: list[str], timeout: int, what: str):
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ConversionError(f"{what} took too long. Try a shorter or smaller file.")
    except subprocess.CalledProcessError:
        raise ConversionError(f"{what} failed. The file may be damaged or in a format we can't read.")


# ---------------------------------------------------------------- OCR

def extract_text(files: list[InputFile], lang: str) -> str:
    if lang not in OCR_LANGS:
        lang = "eng"
    require("tesseract", "Text extraction")

    chunks = []
    for f in files:
        if is_pdf(f):
            doc = pymupdf.open(stream=f.data, filetype="pdf")
            if doc.page_count > OCR_MAX_PAGES:
                raise ConversionError(f"{f.name} has {doc.page_count} pages. The limit is {OCR_MAX_PAGES}.")
            for i, page in enumerate(doc, start=1):
                text = page.get_text().strip()
                if len(text) < 20:  # scanned page: no real text layer, so read the picture
                    pix = page.get_pixmap(dpi=250, alpha=False)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    text = _ocr(img, lang)
                label = f"{f.name}, page {i}" if doc.page_count > 1 else f.name
                chunks.append((label, text))
        else:
            chunks.append((f.name, _ocr(open_image(f), lang)))

    if len(chunks) == 1:
        return chunks[0][1]
    return "\n\n".join(f"--- {label} ---\n{text}" for label, text in chunks)


def _ocr(img: Image.Image, lang: str) -> str:
    img = img.convert("L")
    if max(img.size) < 1200:  # small photos read better enlarged
        scale = 1200 / max(img.size)
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    try:
        return pytesseract.image_to_string(img, lang=lang, timeout=90).strip()
    except RuntimeError:
        raise ConversionError("Reading the text took too long. Try a smaller image or fewer pages.")
    except pytesseract.TesseractError:
        raise ConversionError("Couldn't read text from that file.")


# ---------------------------------------------------------------- video

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".mpeg", ".mpg"}
COMPRESS = {  # level -> (crf, max width)
    "light": (24, 1920),
    "balanced": (28, 1280),
    "strong": (32, 854),
}


def probe_seconds(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
            check=True, capture_output=True, timeout=30,
        )
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        raise ConversionError("That file isn't a video we can read.")


def video(f: InputFile, action: str, level: str, start: float, length: float, width: int) -> OutputFile:
    require("ffmpeg", "Video tools")
    ext = PurePath(f.name).suffix.lower()
    if ext not in VIDEO_EXTS:
        raise ConversionError(f"{f.name} isn't a supported video. Use MP4, MOV, WEBM, MKV or AVI.")

    with tempfile.TemporaryDirectory(prefix="vid-") as tmp:
        src = Path(tmp) / f"input{ext}"
        src.write_bytes(f.data)
        seconds = probe_seconds(src)
        if seconds > VIDEO_MAX_SECONDS:
            raise ConversionError(f"That video is {seconds / 60:.0f} minutes long. The limit is 10 minutes.")

        base = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2"]
        name = stem(f.name)

        if action == "mp3":
            dst, mime, out_name = Path(tmp) / "out.mp3", "audio/mpeg", f"{name}.mp3"
            args = base + ["-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(dst)]
        elif action == "gif":
            start = max(0.0, min(start, seconds))
            length = max(1.0, min(length or 5, GIF_MAX_SECONDS, seconds - start or GIF_MAX_SECONDS))
            width = width if width in (320, 480, 640) else 480
            dst, mime, out_name = Path(tmp) / "out.gif", "image/gif", f"{name}.gif"
            vf = f"fps=12,scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"
            args = base + ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(src), "-vf", vf, "-loop", "0", str(dst)]
        elif action in ("compress", "mp4"):
            crf, max_w = COMPRESS.get(level, COMPRESS["balanced"]) if action == "compress" else (23, 1920)
            dst, mime = Path(tmp) / "out.mp4", "video/mp4"
            out_name = f"{name}-compressed.mp4" if action == "compress" else f"{name}.mp4"
            args = base + [
                "-i", str(src),
                "-vf", f"scale='min({max_w},iw)':-2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k" if action == "mp4" else "96k",
                "-movflags", "+faststart", str(dst),
            ]
        else:
            raise ConversionError("Choose what to do with the video.")

        run(args, timeout=600, what="Processing the video")
        return OutputFile(out_name, dst.read_bytes(), mime)


# ---------------------------------------------------------------- Word -> PDF

DOC_EXTS = {".docx", ".doc", ".odt", ".rtf"}


def word_to_pdf(f: InputFile) -> OutputFile:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ConversionError("Word to PDF isn't available on this server right now.")
    ext = PurePath(f.name).suffix.lower()
    if ext not in DOC_EXTS:
        raise ConversionError(f"{f.name} isn't a Word document. Use .docx, .doc, .odt or .rtf.")

    with tempfile.TemporaryDirectory(prefix="doc-") as tmp:
        src = Path(tmp) / f"input{ext}"
        src.write_bytes(f.data)
        # A private LibreOffice profile per run avoids lock-file clashes.
        profile = Path(tmp, "profile").as_uri()
        run([soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", tmp, str(src)], timeout=120, what="Converting the document")
        out = Path(tmp) / "input.pdf"
        if not out.exists():
            raise ConversionError("Converting the document failed. Try saving it again as .docx.")
        return OutputFile(f"{stem(f.name)}.pdf", out.read_bytes(), "application/pdf")
