"""Validated, versioned counseling playbooks loaded from local data at startup."""
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType

import yaml


@dataclass(frozen=True)
class Playbook:
    id: str
    version: int
    when: str
    body: str


def load_registry(directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).parent
    books = {}
    for path in sorted(directory.glob('*.md')):
        text = path.read_text(encoding='utf-8')
        if not text.startswith('---\n'):
            raise ValueError('playbook front matter required')
        try:
            header, body = text[4:].split('\n---\n', 1)
            metadata = yaml.safe_load(header)
        except (ValueError, yaml.YAMLError):
            raise ValueError('invalid playbook front matter') from None
        if not isinstance(metadata, dict):
            raise ValueError('playbook metadata must be an object')
        id, when = metadata.get('id'), metadata.get('when')
        version = metadata.get('version')
        if (not isinstance(id, str) or not id.strip() or id in books
                or type(version) is not int or version != 1
                or not isinstance(when, str) or not when.strip()
                or not body.strip() or len(body.split()) > 120):
            raise ValueError('invalid or duplicate playbook')
        books[id] = Playbook(id, version, when, body)
    return MappingProxyType(books)


BOOKS = load_registry()


def available_playbooks():
    return '<available_playbooks>' + json.dumps(
        [{'id':book.id, 'when':book.when} for book in BOOKS.values()]
    ) + '</available_playbooks>'


def selected_playbooks(ids):
    if len(ids) > 2:
        raise ValueError('at most two playbooks')
    return json.dumps([{'id':BOOKS[id].id, 'version':BOOKS[id].version,
                       'body':BOOKS[id].body} for id in ids])
