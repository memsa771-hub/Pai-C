"""Page text: HTML and PDF to plain text, links, and the normal form quotes are matched in.

Ported from the Spike 1 harness (spike1-design SP1-D4): the standard-library parser and pypdf, no Docling
(spec S2-D8).
"""

import io
import re
import unicodedata
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin

import yaml
from pypdf import PdfReader

_BLOCK = {"p", "div", "br", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
          "dt", "dd", "table"}
_SKIP = {"script", "style", "noscript", "svg", "template"}


class _TextAndLinks(HTMLParser):
    def __init__(self, base: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base, self.parts, self.links = base, [], []
        self._skip, self._href, self._anchor = 0, None, []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._href, self._anchor = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            url = urldefrag(urljoin(self.base, self._href))[0]
            if url.startswith(("http://", "https://")):
                self.links.append((url, " ".join(a for a in self._anchor if a)))
            self._href = None

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)
            if self._href is not None:
                self._anchor.append(data.strip())


def html_to_text(html: str, base: str) -> tuple[str, list[tuple[str, str]]]:
    """The visible text (one line per block element) and the page's (url, anchor text) links."""
    p = _TextAndLinks(base)
    p.feed(html)
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line), p.links


def pdf_to_text(data: bytes) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages)


NORMALISE_FILE = Path(__file__).with_name("normalise.yaml")


@cache
def _folding(path: Path = NORMALISE_FILE) -> tuple[dict[int, int | None], dict, re.Pattern]:
    """The str.translate table, the language data and the joiner pattern, from `normalise.yaml` (P2-D14)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    table: dict[int, int | None] = {}
    for target, letters in data["fold"].items():
        for ch in letters:
            table[ord(ch)] = ord(target)
    for lo, hi in data["remove"]["ranges"]:
        for cp in range(int(lo, 16), int(hi, 16) + 1):
            table[cp] = None
    for cp in data["remove"]["singles"]:
        table[int(cp, 16)] = None
    for start in data["digits"]:
        for i in range(10):
            table[int(start, 16) + i] = ord(str(i))
    joiners = "".join(chr(int(c, 16)) for c in data["joiners"]["chars"])
    arabic = "".join(f"{chr(int(lo, 16))}-{chr(int(hi, 16))}" for lo, hi in data["joiners"]["next_to"])
    pattern = re.compile(f"(?<=[{arabic}])[{joiners}]|[{joiners}](?=[{arabic}])")
    return table, data, pattern


def detect_language(text: str) -> str | None:
    """The language of a text, only with evidence (see `normalise.yaml`): a language code (`ur`) when the text uses
    enough letters of that language alone; the script tag (`arab`) when most letters are in a listed script but
    there is no such evidence; None otherwise (Latin text, digits, nothing)."""
    _, data, _ = _folding()
    letters = [c for c in unicodedata.normalize("NFC", text) if c.isalpha()]
    if not letters:
        return None
    counts: dict[str, int] = {}
    for c in letters:
        script = unicodedata.name(c, "").split(" ")[0]
        counts[script] = counts.get(script, 0) + 1
    script, n = max(counts.items(), key=lambda kv: kv[1])
    if n / len(letters) < data["min_script_share"] or script not in data["script_tags"]:
        return None
    for code, rule in data["languages"].get(script, {}).items():
        if sum(1 for c in letters if c in rule["letters"]) >= rule["min_letters"]:
            return code
    return data["script_tags"][script]


def normalise(text: str) -> str:
    """Whitespace collapsed, dashes and quotes unified, case folded: the form quotes are matched in.

    Also maps the literal text "\x00a0", which models sometimes write for a non-breaking space (Spike 1).
    """
    text = text.replace("\x00a0", " ").replace("\x00a0", " ").replace(" ", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    table, _, joiners = _folding()
    text = joiners.sub("", unicodedata.normalize("NFC", text)).translate(table)
    return re.sub(r"\s+", " ", text).strip().casefold()
