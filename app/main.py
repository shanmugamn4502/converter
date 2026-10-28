import threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import heavy, images, pdfs, qr
from .convert import ConversionError, InputFile, OutputFile, bundle, convert

MB = 1024 * 1024
STATIC = Path(__file__).parent / "static"

# The server has ~900 MB of RAM. Light tools (Pillow, PyMuPDF) may run two at
# a time; heavy ones (ffmpeg, LibreOffice, Tesseract) one at a time.
light_slots = threading.BoundedSemaphore(2)
heavy_slots = threading.BoundedSemaphore(1)

app = FastAPI(title="File tools", docs_url=None, redoc_url=None)


@contextmanager
def slot(heavy_job: bool = False):
    sem = heavy_slots if heavy_job else light_slots
    if not sem.acquire(timeout=90):
        raise HTTPException(503, "The server is busy with other files. Try again in a minute.")
    try:
        yield
    except ConversionError as e:
        raise HTTPException(400, str(e))
    finally:
        sem.release()


def read(files: list[UploadFile], max_files: int = 20, max_mb: int = 25) -> list[InputFile]:
    if len(files) > max_files:
        raise HTTPException(400, f"You can add up to {max_files} files at a time.")
    out = []
    for upload in files:
        data = upload.file.read(max_mb * MB + 1)
        if len(data) > max_mb * MB:
            raise HTTPException(413, f"{upload.filename} is over {max_mb} MB.")
        out.append(InputFile(upload.filename or "file", data))
    return out


def send(result: OutputFile, original_bytes: int | None = None, **headers: str) -> Response:
    h = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(result.name)}",
        "Cache-Control": "no-store",
        "X-Result-Size": str(len(result.data)),
    }
    if original_bytes is not None:
        h["X-Original-Size"] = str(original_bytes)
    h.update({k.replace("_", "-"): v for k, v in headers.items()})
    return Response(result.data, media_type=result.mime, headers=h)


def one_by_one(inputs: list[InputFile], fn) -> OutputFile:
    return bundle([fn(f) for f in inputs])


def total(inputs: list[InputFile]) -> int:
    return sum(len(f.data) for f in inputs)


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------------------------------------------------------------- convert

@app.post("/api/convert")
def convert_files(files: list[UploadFile] = File(...), target: str = Form(...),
                  quality: int = Form(90), dpi: int = Form(150)):
    inputs = read(files)
    with slot():
        result = bundle(convert(inputs, target.lower(), quality=min(max(quality, 30), 100), dpi=min(max(dpi, 72), 300)))
    return send(result)


# ---------------------------------------------------------------- images

@app.post("/api/image/compress")
def image_compress(files: list[UploadFile] = File(...), level: str = Form("balanced"), target_kb: int = Form(0)):
    inputs = read(files)
    with slot():
        result = one_by_one(inputs, lambda f: images.compress_image(f, level, max(target_kb, 10) if target_kb else None))
    return send(result, total(inputs))


@app.post("/api/image/resize")
def image_resize(files: list[UploadFile] = File(...), width: int = Form(0), height: int = Form(0),
                 percent: int = Form(0), fit: str = Form("contain")):
    inputs = read(files)
    if percent and not 1 <= percent <= 400:
        raise HTTPException(400, "Use a percentage between 1 and 400.")
    with slot():
        result = one_by_one(inputs, lambda f: images.resize_image(f, width or None, height or None, percent or None, fit))
    return send(result)


@app.post("/api/image/crop-rotate")
def image_crop_rotate(files: list[UploadFile] = File(...), rotate: int = Form(0),
                      flip: str = Form("none"), ratio: str = Form("original")):
    inputs = read(files)
    with slot():
        result = one_by_one(inputs, lambda f: images.crop_rotate(f, rotate, flip, ratio))
    return send(result)


@app.post("/api/image/remove-metadata")
def image_remove_metadata(files: list[UploadFile] = File(...)):
    inputs = read(files)
    with slot():
        outs, found = [], set()
        for f in inputs:
            out, removed = images.strip_metadata(f)
            outs.append(out)
            found.update(removed)
        result = bundle(outs)
    return send(result, X_Removed=", ".join(sorted(found)) or "none")


@app.post("/api/image/favicon")
def image_favicon(files: list[UploadFile] = File(...)):
    inputs = read(files, max_files=1)
    with slot():
        result = images.make_favicon(inputs[0])
    return send(result)


# ---------------------------------------------------------------- PDF

@app.post("/api/pdf/merge")
def pdf_merge(files: list[UploadFile] = File(...)):
    inputs = read(files, max_files=30)
    with slot():
        result = pdfs.merge(inputs)
    return send(result)


@app.post("/api/pdf/split")
def pdf_split(files: list[UploadFile] = File(...), mode: str = Form("extract"), ranges: str = Form("")):
    inputs = read(files, max_files=1, max_mb=50)
    with slot():
        result = pdfs.split(inputs[0], mode, ranges)
    return send(result)


@app.post("/api/pdf/compress")
def pdf_compress(files: list[UploadFile] = File(...), level: str = Form("balanced"), target_kb: int = Form(0)):
    inputs = read(files, max_files=1, max_mb=50)
    with slot(heavy_job=True):
        result = pdfs.compress(inputs[0], level, max(target_kb, 50) if target_kb else None)
    return send(result, total(inputs))


@app.post("/api/pdf/from-word")
def pdf_from_word(files: list[UploadFile] = File(...)):
    inputs = read(files, max_files=1, max_mb=20)
    with slot(heavy_job=True):
        result = heavy.word_to_pdf(inputs[0])
    return send(result)


# ---------------------------------------------------------------- video

@app.post("/api/video")
def video_tool(files: list[UploadFile] = File(...), action: str = Form(...), level: str = Form("balanced"),
               start: float = Form(0), length: float = Form(5), width: int = Form(480)):
    inputs = read(files, max_files=1, max_mb=100)
    with slot(heavy_job=True):
        result = heavy.video(inputs[0], action, level, start, length, width)
    return send(result, total(inputs))


# ---------------------------------------------------------------- OCR + QR

@app.post("/api/ocr")
def ocr(files: list[UploadFile] = File(...), lang: str = Form("eng")):
    inputs = read(files, max_files=10)
    with slot(heavy_job=True):
        text = heavy.extract_text(inputs, lang)
    return {"text": text}


@app.post("/api/qr")
def make_qr(kind: str = Form("link"), text: str = Form(""), ssid: str = Form(""), password: str = Form(""),
            security: str = Form("WPA"), upi: str = Form(""), payee: str = Form(""), amount: str = Form(""),
            note: str = Form(""), fmt: str = Form("png"), color: str = Form("#17203a")):
    fields = dict(text=text, ssid=ssid, password=password, security=security, upi=upi, payee=payee,
                  amount=amount, note=note)
    with slot():
        result = qr.make_qr(kind, fields, fmt, color)
    return send(result)


# ---------------------------------------------------------------- page

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
