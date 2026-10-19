"""Loads playbook YAML files. Any problem is a PlaybookError naming the file, so startup fails loudly."""

from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.os.playbooks.models import Playbook

PLAYBOOK_DIR = Path(__file__).parent


class PlaybookError(ValueError):
    pass


def load_playbook(path: Path) -> Playbook:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
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
    return books


def select_playbook(
    books: Mapping[tuple[str, int], Playbook], origin: str, destination: str, level: str
) -> Playbook:
    matches = [
        b for b in books.values()
        if (b.route.origin, b.route.destination, b.route.level) == (origin, destination, level)
    ]
    if not matches:
        raise PlaybookError(f"no playbook for {origin}->{destination} {level}")
    return max(matches, key=lambda b: (b.version, b.key))
