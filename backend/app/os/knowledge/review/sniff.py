"""Decides what an uploaded evidence file is from its bytes, never from the client's claim (P2-T5, C1)."""

PDF = b"%PDF-"
PNG = b"\x89PNG\r\n\x1a\n"


def sniff(data: bytes) -> str | None:
    """The content type the bytes show, or None when they are none of the passive types we accept."""
    if data.startswith(PDF):
        return "application/pdf"
    if data.startswith(PNG):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\x00" in text:
        return None
    return "text/plain"


def safe_disposition(kind: str, filename: str) -> str:
    """A Content-Disposition value with an ASCII fallback and the full name as RFC 5987 `filename*`."""
    from urllib.parse import quote

    ascii_name = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in filename)[:150] or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"
