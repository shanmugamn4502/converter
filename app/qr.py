"""QR codes for links, text, Wi-Fi and UPI payments."""

import io
import re
from urllib.parse import quote

import segno
import segno.helpers

from .convert import ConversionError, OutputFile

UPI_ID = re.compile(r"^[\w.\-]{2,256}@[A-Za-z]{2,64}$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def upi_uri(parts: list[str]) -> str:
    return "upi://pay?" + "&".join(parts)


def payload(kind: str, fields: dict[str, str]):
    v = {k: (fields.get(k) or "").strip() for k in ("text", "ssid", "password", "security", "upi", "payee", "amount", "note")}

    if kind in ("text", "link"):
        if not v["text"]:
            raise ConversionError("Type the text or link to put in the QR code.")
        if len(v["text"]) > 1500:
            raise ConversionError("That's too long for a QR code. Keep it under 1,500 characters.")
        return segno.make(v["text"], error="m")

    if kind == "wifi":
        if not v["ssid"]:
            raise ConversionError("Enter the Wi-Fi network name.")
        security = v["security"] if v["security"] in ("WPA", "WEP") else None
        return segno.helpers.make_wifi(ssid=v["ssid"], password=v["password"] or None,
                                       security=security if v["password"] else "nopass")

    if kind == "upi":
        if not UPI_ID.match(v["upi"]):
            raise ConversionError("Enter a valid UPI ID, like name@okbank.")
        parts = [f"pa={quote(v['upi'], safe='@.')}", f"pn={quote(v['payee'] or v['upi'].split('@')[0])}"]
        if v["amount"]:
            if not re.fullmatch(r"\d{1,7}(\.\d{1,2})?", v["amount"]):
                raise ConversionError("Enter the amount as a number, like 250 or 99.50.")
            parts.append(f"am={v['amount']}")
        parts.append("cu=INR")
        if v["note"]:
            parts.append(f"tn={quote(v['note'][:60])}")
        return segno.make(upi_uri(parts), error="m")

    raise ConversionError("Choose what the QR code is for.")


def make_qr(kind: str, fields: dict[str, str], fmt: str, color: str) -> OutputFile:
    qr = payload(kind, fields)
    dark = color if HEX.match(color or "") else "#17203a"
    out = io.BytesIO()
    if fmt == "svg":
        qr.save(out, kind="svg", scale=10, border=4, dark=dark, light="#ffffff", xmldecl=False)
        return OutputFile("qr-code.svg", out.getvalue(), "image/svg+xml")
    qr.save(out, kind="png", scale=16, border=4, dark=dark, light="#ffffff")
    return OutputFile("qr-code.png", out.getvalue(), "image/png")
