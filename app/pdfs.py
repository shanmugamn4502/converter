"""PDF tools: merge, split, compress."""

import io
import re
import zipfile

import pymupdf

from .convert import MAX_PDF_PAGES, ConversionError, InputFile, OutputFile, is_pdf, stem

MAX_MERGE_PAGES = 300


def open_pdf(f: InputFile, max_pages: int = MAX_PDF_PAGES * 4) -> pymupdf.Document:
    if not is_pdf(f):
        raise ConversionError(f"{f.name} isn't a PDF.")
    try:
        doc = pymupdf.open(stream=f.data, filetype="pdf")
    except Exception:
        raise ConversionError(f"{f.name} can't be opened. It may be damaged.")
    if doc.needs_pass:
        raise ConversionError(f"{f.name} is password-protected. Remove the password and try again.")
    if doc.page_count > max_pages:
        raise ConversionError(f"{f.name} has {doc.page_count} pages. The limit is {max_pages}.")
    return doc


def pdf_bytes(doc: pymupdf.Document) -> bytes:
    return doc.tobytes(garbage=4, deflate=True, clean=True)


def merge(files: list[InputFile]) -> OutputFile:
    if len(files) < 2:
        raise ConversionError("Add at least two PDFs to merge.")
    out = pymupdf.open()
    for f in files:
        src = open_pdf(f)
        if out.page_count + src.page_count > MAX_MERGE_PAGES:
            raise ConversionError(f"The merged PDF would be over {MAX_MERGE_PAGES} pages.")
        out.insert_pdf(src)
        src.close()
    return OutputFile("merged.pdf", pdf_bytes(out), "application/pdf")


def parse_pages(spec: str, count: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based page numbers, in the order written."""
    pages: list[int] = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        m = re.fullmatch(r"(\d+)?\s*(-)?\s*(\d+)?", part)
        if not m or not (m.group(1) or m.group(3)):
            raise ConversionError(f'"{part}" isn\'t a page number or range. Use something like 1-3, 5.')
        a = int(m.group(1) or 1)
        b = int(m.group(3) or count) if m.group(2) else a
        if a < 1 or b > count or a > b:
            raise ConversionError(f"Pages {part} don't exist. This PDF has {count} pages.")
        pages += range(a - 1, b)
    if not pages:
        raise ConversionError("Enter the pages to keep, like 1-3, 5.")
    return pages


def split(f: InputFile, mode: str, ranges: str) -> OutputFile:
    doc = open_pdf(f)
    if mode == "every":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(doc.page_count):
                one = pymupdf.open()
                one.insert_pdf(doc, from_page=i, to_page=i)
                z.writestr(f"{stem(f.name)}-page-{i + 1}.pdf", pdf_bytes(one))
        return OutputFile(f"{stem(f.name)}-pages.zip", buf.getvalue(), "application/zip")

    pages = parse_pages(ranges, doc.page_count)
    doc.select(pages)
    return OutputFile(f"{stem(f.name)}-selected.pdf", pdf_bytes(doc), "application/pdf")


PDF_LEVELS = {  # level -> (image dpi, jpeg quality)
    "light": (150, 80),
    "balanced": (110, 65),
    "strong": (80, 50),
}


def _shrink(data: bytes, dpi: int, quality: int) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    doc.rewrite_images(dpi_threshold=dpi + 10, dpi_target=dpi, quality=quality)
    return pdf_bytes(doc)


def compress(f: InputFile, level: str, target_kb: int | None) -> OutputFile:
    open_pdf(f).close()  # validates
    name = f"{stem(f.name)}-compressed.pdf"

    if target_kb:
        limit = target_kb * 1024
        best = f.data
        for dpi, q in [(150, 80), (120, 70), (100, 60), (80, 50), (72, 40), (60, 35)]:
            best = min(best, _shrink(f.data, dpi, q), key=len)
            if len(best) <= limit:
                return OutputFile(name, best, "application/pdf")
        raise ConversionError(
            f"The smallest we could get is {len(best) // 1024} KB, still over {target_kb} KB. "
            "Try splitting the PDF into parts."
        )

    dpi, q = PDF_LEVELS.get(level, PDF_LEVELS["balanced"])
    data = _shrink(f.data, dpi, q)
    return OutputFile(name, min(data, f.data, key=len), "application/pdf")
