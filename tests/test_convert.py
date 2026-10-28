import io
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.convert import ConversionError, InputFile, bundle, convert
from app.main import app


def png(size=(40, 30), mode="RGBA", color=(255, 0, 0, 128)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, "PNG")
    return buf.getvalue()


def pdf(pages=2):
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}")
    return doc.tobytes()


def opened(data):
    return Image.open(io.BytesIO(data))


@pytest.mark.parametrize("target,fmt", [
    ("jpg", "JPEG"), ("png", "PNG"), ("webp", "WEBP"), ("gif", "GIF"),
    ("bmp", "BMP"), ("tiff", "TIFF"), ("ico", "ICO"),
])
def test_png_to_every_image_format(target, fmt):
    [out] = convert([InputFile("photo.png", png())], target)
    assert out.name == f"photo.{target}"
    assert opened(out.data).format == fmt


def test_transparent_png_to_jpg_is_flattened_on_white():
    [out] = convert([InputFile("a.png", png(color=(0, 0, 0, 0)))], "jpg")
    assert opened(out.data).getpixel((0, 0)) == (255, 255, 255)


def test_pdf_to_images_one_file_per_page():
    outs = convert([InputFile("report.pdf", pdf(3))], "png", dpi=72)
    assert [o.name for o in outs] == ["report-page-1.png", "report-page-2.png", "report-page-3.png"]
    assert opened(outs[0].data).size == (595, 842)  # A4 page at 72 dpi


def test_images_to_single_pdf():
    [out] = convert([InputFile("a.png", png()), InputFile("b.png", png())], "pdf")
    assert out.name == "combined.pdf"
    assert pymupdf.open(stream=out.data, filetype="pdf").page_count == 2


def test_pdf_to_pdf_is_rejected():
    with pytest.raises(ConversionError):
        convert([InputFile("a.pdf", pdf())], "pdf")


def test_garbage_is_rejected_with_friendly_message():
    with pytest.raises(ConversionError, match="notes.txt"):
        convert([InputFile("notes.txt", b"hello")], "png")


def test_bundle_zips_multiple_and_dedupes_names():
    outs = convert([InputFile("x.png", png()), InputFile("x.png", png())], "jpg")
    z = zipfile.ZipFile(io.BytesIO(bundle(outs).data))
    assert sorted(z.namelist()) == ["x-2.jpg", "x.jpg"]


def test_api_returns_download():
    client = TestClient(app)
    r = client.post("/api/convert", data={"target": "jpg"}, files=[("files", ("cat.png", png(), "image/png"))])
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert "cat.jpg" in r.headers["content-disposition"]


def test_api_reports_errors_as_400():
    client = TestClient(app)
    r = client.post("/api/convert", data={"target": "png"}, files=[("files", ("x.txt", b"nope", "text/plain"))])
    assert r.status_code == 400
    assert "x.txt" in r.json()["detail"]
