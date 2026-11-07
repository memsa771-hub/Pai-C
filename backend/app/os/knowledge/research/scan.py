"""The `ScanText` port: text from a scanned notice or an image-only PDF (P2 spec §4.3, P2-D13; R-29, R-72).

An adapter reads ONE page image and returns text. `scan_document` handles an image file or a PDF (rasterised with
pypdfium2, a page cap from settings). Machine-read text keeps `read_method: ocr`, and its facts stay `unconfirmed`
until a checker compares them with the original (R-72): see `readability.machine_status_ceiling`.

Adapters: `FixedScanText` (a fake for tests and offline runs), `TesseractScanText` (the `tesseract` command, local),
`DoclingScanText` (local; written against Docling's documented API and NOT run in the P2-T4 environment, where Docling
is not installed). A paid vision adapter is deliberately not here: it needs the owner's cost cap (spec §11 Q5).
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Protocol

import yaml

LANGUAGES_FILE = Path(__file__).with_name("scan_languages.yaml")
IMAGE_TYPES = ("image/png", "image/jpeg", "image/tiff", "image/webp", "image/bmp")


class ScanFailed(Exception):
    """The engine could not read the image (crashed, timed out, returned nothing)."""


@dataclass(frozen=True)
class ScanResult:
    text: str
    engine: str
    language: str | None = None
    confidence: float | None = None  # 0..1 when the engine reports one


class ScanText(Protocol):
    name: str

    def available(self) -> bool: ...

    def scan(self, image: bytes, *, languages: Sequence[str] = ()) -> ScanResult: ...


@cache
def _languages() -> dict:
    return yaml.safe_load(LANGUAGES_FILE.read_text(encoding="utf-8"))


def default_languages() -> tuple[str, ...]:
    return tuple(_languages()["default_languages"])


def _engine_codes(engine: str, languages: Sequence[str]) -> list[str]:
    table = _languages()[engine]
    langs = languages or default_languages()
    unknown = [lang for lang in langs if lang not in table]
    if unknown:
        raise ScanFailed(f"{engine} has no code for language(s) {unknown}")
    return [table[lang] for lang in langs]


class FixedScanText:
    """A fake engine: answers from a table keyed by the SHA-256 of the image bytes, or one text for every image.
    `fail_on` is a set of hashes that raise ScanFailed."""
    name = "fixed"

    def __init__(self, texts: Mapping[str, str] | str, fail_on: Sequence[str] = ()) -> None:
        self.texts, self.fail_on, self.calls = texts, set(fail_on), []

    def available(self) -> bool:
        return True

    def scan(self, image: bytes, *, languages: Sequence[str] = ()) -> ScanResult:
        key = hashlib.sha256(image).hexdigest()
        self.calls.append(key)
        if key in self.fail_on:
            raise ScanFailed("fixed: asked to fail")
        text = self.texts if isinstance(self.texts, str) else self.texts.get(key, "")
        return ScanResult(text, self.name)


class TesseractScanText:
    """The `tesseract` command line (local, no model cost). Needs the binary and the language data (eng, urd)."""
    name = "tesseract"

    def __init__(self, command: str = "tesseract", timeout_s: float = 60.0,
                 run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.command, self.timeout_s, self._run = command, timeout_s, run

    def available(self) -> bool:
        return shutil.which(self.command) is not None

    def scan(self, image: bytes, *, languages: Sequence[str] = ()) -> ScanResult:
        codes = "+".join(_engine_codes("tesseract", languages))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "page"
            path.write_bytes(image)
            try:
                done = self._run([self.command, str(path), "stdout", "-l", codes], capture_output=True,
                                 timeout=self.timeout_s, check=False)
            except (OSError, subprocess.TimeoutExpired) as e:
                raise ScanFailed(f"tesseract: {type(e).__name__}") from e
        if done.returncode != 0:
            raise ScanFailed(f"tesseract exited {done.returncode}")
        return ScanResult(done.stdout.decode("utf-8", errors="replace").strip(), self.name)


class DoclingScanText:
    """Docling (local). UNVERIFIED here: Docling is not installed in the P2-T4 environment, so this follows the
    documented `DocumentConverter().convert(path).document.export_to_text()` call and its tests skip."""
    name = "docling"

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def scan(self, image: bytes, *, languages: Sequence[str] = ()) -> ScanResult:
        codes = _engine_codes("docling", languages)
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                EasyOcrOptions,
                PdfPipelineOptions,
            )
            from docling.document_converter import DocumentConverter, ImageFormatOption

            options = PdfPipelineOptions(do_ocr=True, ocr_options=EasyOcrOptions(lang=codes))
            converter = DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "page.png"
                path.write_bytes(image)
                text = converter.convert(str(path)).document.export_to_text()
        except ScanFailed:
            raise
        except Exception as e:
            raise ScanFailed(f"docling: {type(e).__name__}") from e
        return ScanResult(text.strip(), self.name)


def rasterise_pdf(data: bytes, max_pages: int, scale: float = 2.0) -> list[bytes]:
    """The first `max_pages` pages of a PDF as PNG images (pypdfium2)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        out = []
        for i in range(min(len(pdf), max_pages)):
            buf = io.BytesIO()
            pdf[i].render(scale=scale).to_pil().save(buf, format="PNG")
            out.append(buf.getvalue())
        return out
    finally:
        pdf.close()


def scan_document(scanner: ScanText, data: bytes, content_type: str, *, max_pages: int = 10,
                  languages: Sequence[str] = ()) -> ScanResult:
    """An image file or a PDF through the scanner. Pages are joined by a blank line. Empty text is a failure."""
    kind = content_type.split(";")[0].strip().lower()
    if kind == "application/pdf":
        try:
            images = rasterise_pdf(data, max_pages)
        except Exception as e:
            raise ScanFailed(f"rasterise: {type(e).__name__}") from e
    elif kind in IMAGE_TYPES:
        images = [data]
    else:
        raise ScanFailed(f"not a scannable type: {kind}")
    results = [scanner.scan(img, languages=languages) for img in images]
    text = "\n\n".join(r.text for r in results if r.text.strip())
    if not text.strip():
        raise ScanFailed(f"{scanner.name}: no text found")
    return ScanResult(text, scanner.name)
