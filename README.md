# Converter

Free file tools: change format, compress, resize, crop, remove photo location data,
favicons, merge/split/compress PDFs, Word to PDF, video to MP3/GIF/MP4, text from
images (OCR) and QR codes. Files are processed in memory or a temp folder and
deleted straight after.

FastAPI + Pillow + PyMuPDF, with ffmpeg, Tesseract and LibreOffice for the heavy tools.
Plain HTML/CSS/JS front end in `app/static/`.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8765
```

Optional system programs: `ffmpeg`, `tesseract-ocr` (+ `-tam`, `-hin`), `libreoffice-writer-nogui`.

## Tests

```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest -q
```

## Deploy

Pushing to `main` runs the tests, uploads the code to the server, installs
requirements and restarts the `converter` service (see `.github/workflows/deploy.yml`).
Server config lives in `deploy/`: a systemd unit and the nginx reverse-proxy block.
