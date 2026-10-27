"""The pilot terms: `pilot.vN.md` files with front matter (`version`, `placeholder`); the highest N is current.

The owners write the text (spec §10 Q2). Until then `pilot.v1.md` is a placeholder, which the API refuses outside
rehearsal mode. The text holds no country words (invariant 12)."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

CONSENT_DIR = Path(__file__).parent
_NAME = re.compile(r"^pilot\.v([1-9][0-9]*)\.md$")
_FRONT = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Terms:
    version: int
    text: str
    placeholder: bool


def current_terms(terms_dir: Path | str | None = None) -> Terms:
    """Reads the highest `pilot.vN.md` in `terms_dir` (default: this package). Read on every call, so a new version
    counts at once. Raises ValueError for no file, missing front matter, or a version that differs from the name."""
    folder = Path(terms_dir) if terms_dir is not None else CONSENT_DIR
    found = [(int(m.group(1)), p) for p in (folder.iterdir() if folder.is_dir() else ())
             if (m := _NAME.match(p.name))]
    if not found:
        raise ValueError(f"no pilot terms (pilot.vN.md) in {folder}")
    number, path = max(found)
    m = _FRONT.match(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    meta = (yaml.safe_load(m.group(1)) if m else None) or {}
    if type(meta) is not dict or type(meta.get("placeholder")) is not bool:
        raise ValueError(f"{path.name}: front matter needs version and placeholder (true or false)")
    if meta.get("version") != number:
        raise ValueError(f"{path.name}: front matter version {meta.get('version')!r} does not match the file name")
    text = m.group(2).strip()
    if not text:
        raise ValueError(f"{path.name}: the terms text is empty")
    return Terms(version=number, text=text, placeholder=meta["placeholder"])
