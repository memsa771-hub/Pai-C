"""Page text: HTML and PDF to plain text, links, and the normal form quotes are matched in.

Ported from the Spike 1 harness (spike1-design SP1-D4): the standard-library parser and pypdf, no Docling
(spec S2-D8).
"""

import io
import re
from html.parser import HTMLParser
from urllib.parse import urldefrag, urljoin

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


def normalise(text: str) -> str:
    """Whitespace collapsed, dashes and quotes unified, case folded: the form quotes are matched in.

    Also maps the literal text "\x00a0", which models sometimes write for a non-breaking space (Spike 1).
    """
    text = text.replace("\x00a0", " ").replace("\x00a0", " ").replace(" ", " ")
    text = text.replace("–", "-").replace("—", "-")
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().casefold()
