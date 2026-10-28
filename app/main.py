import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .convert import ConversionError, InputFile, bundle, convert

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 20
STATIC = Path(__file__).parent / "static"

# At most two conversions at once, so a burst of uploads can't run the
# small server out of memory. Others wait their turn.
slots = threading.BoundedSemaphore(2)

app = FastAPI(title="File Converter", docs_url=None, redoc_url=None)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/convert")
def convert_files(
    files: list[UploadFile] = File(...),
    target: str = Form(...),
    quality: int = Form(90),
    dpi: int = Form(150),
):
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"You can convert up to {MAX_FILES} files at a time.")
    quality = min(max(quality, 30), 100)
    dpi = min(max(dpi, 72), 300)

    inputs = []
    for upload in files:
        data = upload.file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{upload.filename} is over 25 MB.")
        inputs.append(InputFile(upload.filename or "file", data))

    with slots:
        try:
            result = bundle(convert(inputs, target.lower(), quality=quality, dpi=dpi))
        except ConversionError as e:
            raise HTTPException(400, str(e))

    return Response(
        result.data,
        media_type=result.mime,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(result.name)}",
            "Cache-Control": "no-store",
        },
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
