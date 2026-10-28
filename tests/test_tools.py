import io
import shutil
import subprocess
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app import heavy, images, pdfs, qr
from app.convert import ConversionError, InputFile
from app.main import app

client = TestClient(app)


def photo(size=(1600, 1200), fmt="JPEG", exif=True):
    img = Image.new("RGB", size)
    # noisy content so compression has something to do
    img.putdata([((x * 7) % 256, (y * 5) % 256, (x * y) % 256) for y in range(size[1]) for x in range(size[0])])
    buf = io.BytesIO()
    kw = {}
    if exif:
        e = Image.Exif()
        e[271] = "PhoneMaker"
        e[272] = "Model X"
        e[306] = "2026:01:01 10:00:00"
        e[34853] = {1: "N", 2: (13.0, 5.0, 0.0)}
        kw["exif"] = e
    img.save(buf, fmt, quality=95, **kw)
    return buf.getvalue()


def pdf(pages=3, with_image=False):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
        if with_image:
            page.insert_image(page.rect, stream=photo((1200, 1600), exif=False))
    return doc.tobytes()


def pages_of(data):
    return pymupdf.open(stream=data, filetype="pdf").page_count


# ---------------------------------------------------------------- images

def test_compress_balanced_makes_photo_smaller():
    src = photo()
    out = images.compress_image(InputFile("p.jpg", src), "balanced", None)
    assert len(out.data) < len(src)
    assert out.name == "p-compressed.jpg"


def test_compress_to_target_size():
    out = images.compress_image(InputFile("p.jpg", photo()), "balanced", 60)
    assert len(out.data) <= 60 * 1024


def test_compress_strips_exif():
    out = images.compress_image(InputFile("p.jpg", photo()), "light", None)
    assert not Image.open(io.BytesIO(out.data)).getexif()


def test_resize_exact_cover_and_percent():
    src = InputFile("p.jpg", photo((800, 600), exif=False))
    assert Image.open(io.BytesIO(images.resize_image(src, 413, 531, None, "cover").data)).size == (413, 531)
    assert Image.open(io.BytesIO(images.resize_image(src, None, None, 50, "contain").data)).size == (400, 300)
    assert Image.open(io.BytesIO(images.resize_image(src, 200, None, None, "contain").data)).size == (200, 150)


def test_rotate_and_square_crop():
    src = InputFile("p.jpg", photo((800, 600), exif=False))
    out = images.crop_rotate(src, 90, "none", "original")
    assert Image.open(io.BytesIO(out.data)).size == (600, 800)
    out = images.crop_rotate(src, 0, "horizontal", "1:1")
    assert Image.open(io.BytesIO(out.data)).size == (600, 600)


def test_remove_metadata_reports_and_removes():
    out, found = images.strip_metadata(InputFile("p.jpg", photo((200, 100))))
    assert set(found) >= {"location", "camera model", "date taken"}
    assert not Image.open(io.BytesIO(out.data)).getexif()


def test_favicon_zip_contents():
    out = images.make_favicon(InputFile("logo.png", photo((300, 200), "PNG", exif=False)))
    names = zipfile.ZipFile(io.BytesIO(out.data)).namelist()
    assert {"favicon.ico", "apple-touch-icon.png", "android-chrome-512x512.png", "paste-into-head.html"} <= set(names)


# ---------------------------------------------------------------- PDF

def test_merge_keeps_order_and_pages():
    out = pdfs.merge([InputFile("a.pdf", pdf(2)), InputFile("b.pdf", pdf(3))])
    doc = pymupdf.open(stream=out.data, filetype="pdf")
    assert doc.page_count == 5
    assert "Page 1" in doc[2].get_text()  # first page of b.pdf


def test_merge_needs_two():
    with pytest.raises(ConversionError):
        pdfs.merge([InputFile("a.pdf", pdf(1))])


@pytest.mark.parametrize("spec,expected", [("1-3", [0, 1, 2]), ("2, 4-", [1, 3, 4]), ("5,1", [4, 0])])
def test_parse_pages(spec, expected):
    assert pdfs.parse_pages(spec, 5) == expected


@pytest.mark.parametrize("spec", ["0", "6", "3-2", "abc", ""])
def test_parse_pages_rejects_bad_input(spec):
    with pytest.raises(ConversionError):
        pdfs.parse_pages(spec, 5)


def test_split_extract_and_every():
    src = InputFile("doc.pdf", pdf(4))
    assert pages_of(pdfs.split(src, "extract", "2-3").data) == 2
    z = zipfile.ZipFile(io.BytesIO(pdfs.split(src, "every", "").data))
    assert len(z.namelist()) == 4


def test_compress_pdf_with_images_shrinks():
    src = pdf(2, with_image=True)
    out = pdfs.compress(InputFile("scan.pdf", src), "strong", None)
    assert len(out.data) < len(src)
    assert pages_of(out.data) == 2


# ---------------------------------------------------------------- QR

def test_qr_link_png():
    out = qr.make_qr("link", {"text": "https://shanmugam.is-a.dev"}, "png", "#17203a")
    assert Image.open(io.BytesIO(out.data)).format == "PNG"


def test_qr_upi_and_wifi_build_payloads(monkeypatch):
    seen = []
    monkeypatch.setattr(qr, "upi_uri", lambda parts: seen.append(qr_uri := "upi://pay?" + "&".join(parts)) or qr_uri)
    qr.payload("upi", {"upi": "shan@okaxis", "payee": "Shan", "amount": "250", "note": "Order 42"})
    assert seen == ["upi://pay?pa=shan@okaxis&pn=Shan&am=250&cu=INR&tn=Order%2042"]
    wifi = qr.payload("wifi", {"ssid": "Home", "password": "secret", "security": "WPA"})
    assert wifi


def test_qr_rejects_bad_upi():
    with pytest.raises(ConversionError, match="UPI ID"):
        qr.payload("upi", {"upi": "not-an-id"})


# ---------------------------------------------------------------- heavy tools (skip if program missing)

needs = lambda prog: pytest.mark.skipif(not shutil.which(prog), reason=f"{prog} not installed")


@needs("tesseract")
def test_ocr_reads_printed_text():
    img = Image.new("RGB", (900, 200), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 64)
    except OSError:
        font = ImageFont.load_default(size=64)
    d.text((30, 60), "Hello Chennai 2026", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    text = heavy.extract_text([InputFile("t.png", buf.getvalue())], "eng")
    assert "Chennai" in text


@needs("ffmpeg")
@pytest.mark.parametrize("action,mime", [("mp3", "audio/mpeg"), ("gif", "image/gif"), ("compress", "video/mp4"), ("mp4", "video/mp4")])
def test_video_actions(tmp_path, action, mime):
    src = tmp_path / "clip.mov"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264",
                    "-c:a", "aac", str(src)], check=True)
    out = heavy.video(InputFile("clip.mov", src.read_bytes()), action, "balanced", 0, 1, 320)
    assert out.mime == mime and len(out.data) > 1000


def test_video_rejects_non_video():
    with pytest.raises(ConversionError):
        heavy.video(InputFile("notes.txt", b"hi"), "mp3", "balanced", 0, 5, 480)


@needs("soffice")
def test_word_to_pdf(tmp_path):
    rtf = rb"{\rtf1\ansi Hello from a document.\par}"
    out = heavy.word_to_pdf(InputFile("letter.rtf", rtf))
    assert out.name == "letter.pdf" and out.data[:5] == b"%PDF-"


# ---------------------------------------------------------------- API wiring

def test_api_compress_reports_sizes():
    r = client.post("/api/image/compress", data={"level": "strong"}, files=[("files", ("p.jpg", photo(), "image/jpeg"))])
    assert r.status_code == 200
    assert int(r.headers["x-result-size"]) < int(r.headers["x-original-size"])


def test_api_remove_metadata_header():
    r = client.post("/api/image/remove-metadata", files=[("files", ("p.jpg", photo((100, 100)), "image/jpeg"))])
    assert "location" in r.headers["x-removed"]


def test_api_split_bad_range_is_friendly():
    r = client.post("/api/pdf/split", data={"mode": "extract", "ranges": "9"}, files=[("files", ("d.pdf", pdf(3), "application/pdf"))])
    assert r.status_code == 400
    assert "3 pages" in r.json()["detail"]


def test_api_qr():
    r = client.post("/api/qr", data={"kind": "wifi", "ssid": "Home", "password": "pw"})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_api_rejects_oversize_video():
    big = b"0" * (101 * 1024 * 1024)
    r = client.post("/api/video", data={"action": "mp3"}, files=[("files", ("v.mp4", big, "video/mp4"))])
    assert r.status_code == 413
