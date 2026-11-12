"""Loads playbook YAML files. Any problem is a PlaybookError naming the file, so startup fails loudly."""

from collections.abc import Iterable, Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.os.playbooks.models import Playbook

PLAYBOOK_DIR = Path(__file__).parent


class PlaybookError(ValueError):
    pass


PAGES_DIR = "pages"  # beside the playbooks: <dir>/pages/<key>.v<version>.yaml holds that version's display data
_SIDECAR_FIELDS = frozenset({"pages", "sources"})


def _sidecar(path: Path, data: dict) -> dict:
    """The playbook's display data, joined by (key, version); a playbook with no sidecar has none."""
    side = path.parent / PAGES_DIR / f"{data.get('key')}.v{data.get('version')}.yaml"
    if not side.is_file():
        return data
    extra = yaml.safe_load(side.read_text(encoding="utf-8")) or {}
    if not isinstance(extra, dict) or not set(extra) <= _SIDECAR_FIELDS:
        raise PlaybookError(f"{side.name}: only {sorted(_SIDECAR_FIELDS)} may be declared here")
    if _SIDECAR_FIELDS & set(data):
        raise PlaybookError(f"{path.name}: {sorted(_SIDECAR_FIELDS & set(data))} belong in {side.name}, not here")
    return {**data, **extra}


def load_playbook(path: Path) -> Playbook:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = _sidecar(path, data)
        return Playbook.model_validate(data)
    except yaml.YAMLError as e:
        raise PlaybookError(f"{path.name}: invalid YAML: {e}") from e
    except ValidationError as e:
        raise PlaybookError(f"{path.name}: {e}") from e


def load_playbook_dir(directory: Path = PLAYBOOK_DIR) -> dict[tuple[str, int], Playbook]:
    books: dict[tuple[str, int], Playbook] = {}
    for path in sorted(directory.glob("*.yaml")):
        book = load_playbook(path)
        ident = (book.key, book.version)
        if ident in books:
            raise PlaybookError(f"{path.name}: duplicate playbook {book.key} v{book.version}")
        books[ident] = book
    side_dir = directory / PAGES_DIR
    if side_dir.is_dir():
        for side in sorted(side_dir.glob("*.yaml")):
            if not any(side.name == f"{k}.v{v}.yaml" for k, v in books):
                raise PlaybookError(f"{side.name}: no playbook of that key and version")
    return books


def select_playbook(
    books: Mapping[tuple[str, int], Playbook], origin: str, destination: str, level: str, *, with_needs: bool = False,
    intake: tuple[str, int] | None = None,
) -> Playbook:
    """The newest playbook for the route. A playbook that declares `needs` is chosen only when the caller asks
    (`with_needs`), and the caller asks only while the student's needs gate is on (P1-T8, D-w3).
    `intake` (term, year): a version whose `applies_to` does not cover it is left out (P2-D25, R-65); without it
    `applies_to` is ignored and the newest wins, as before."""
    matches = [
        b for b in books.values()
        if (b.route.origin, b.route.destination, b.route.level) == (origin, destination, level)
        and (with_needs or not b.declares_needs)
        and (intake is None or b.applies_to is None or b.applies_to.covers(*intake))
    ]
    if not matches:
        raise PlaybookError(f"no playbook for {origin}->{destination} {level}")
    return max(matches, key=lambda b: (b.version, b.key))


def newest_plain(books: Iterable[Playbook]) -> dict[str, Playbook]:
    """The newest version of each playbook key, leaving out the ones that declare `needs`: the route listings and the
    route builder read this, so they stay as they were in every state."""
    out: dict[str, Playbook] = {}
    for book in books:
        if book.declares_needs:
            continue
        if book.key not in out or book.version > out[book.key].version:
            out[book.key] = book
    return out
