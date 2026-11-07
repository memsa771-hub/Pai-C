"""A registry entry and the rules every entry follows (P2 spec §4.1; R-32, R-33, R-60, R-76).

Kinds are generic concepts and live here; their instances (names, regions, domains) are data. A region is a code of
the vocabulary in `knowledge/regions.yaml`. No country, region or body name is written in code (R-58).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.os import models
from app.os.knowledge import regions as region_vocabulary

KIND_PREFIX: dict[str, str] = {
    "regulator": "reg", "board": "board", "admission_body": "body", "admission_system": "sys",
    "entry_test": "test", "institution": "inst", "campus": "campus", "seat_category": "cat", "calendar": "cal",
    "official_list": "list",
}
assert tuple(KIND_PREFIX) == models.REGISTRY_KINDS
KINDS = models.REGISTRY_KINDS
STATUSES = models.REGISTRY_STATUSES
NAMES_A_LIST = ("institution", "campus")  # R-32: built only from official lists, so each names the lists it came from
REGION_REQUIRED = ("regulator", "board", "admission_body", "institution", "campus", "official_list")
NEEDS_PARENT = ("campus",)
NO_QUOTE_NEEDED = ("official_list",)  # a list is the source itself; its count may come with no quote (R-35a)

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_TYPE = re.compile(r"^[a-z][a-z0-9_]*$")


def slug(text: str) -> str:
    """A stable id part from a name: lower case, words joined by '-'. Raises when nothing is left."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    if not s:
        raise ValueError(f"no usable id from '{text}'")
    return s


def known_region(code: str) -> bool:
    return any(code == r.code for country in region_vocabulary.countries() for r in region_vocabulary.regions(country))


@dataclass(frozen=True)
class RegistryEntry:
    entity_id: str
    kind: str
    name: str
    source_url: str
    checked_at: datetime
    quote: str = ""
    parent_id: str | None = None
    region: str | None = None
    institution_type: str | None = None
    aliases: tuple[str, ...] = ()
    official_domains: tuple[str, ...] = ()
    status: str = "active"
    successor_id: str | None = None
    list_ids: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown registry kind '{self.kind}'")
        prefix, _, rest = self.entity_id.partition(":")
        if prefix != KIND_PREFIX[self.kind]:
            raise ValueError(f"id '{self.entity_id}' must use the prefix '{KIND_PREFIX[self.kind]}:' for a {self.kind}")
        if not _SLUG.match(rest):
            raise ValueError(f"id '{self.entity_id}' must be '{prefix}:' and a lower case slug")
        if not self.name.strip():
            raise ValueError("an entry needs a name")
        if self.status not in STATUSES:
            raise ValueError(f"unknown registry status '{self.status}'")
        if (self.status in ("merged", "renamed")) != (self.successor_id is not None):
            raise ValueError("a merged or renamed entity names its successor, and only those do")
        if not self.source_url.strip():
            raise ValueError("an entry needs its official source URL")
        if not self.source_url.startswith("https://"):
            raise ValueError(f"source URL must use https: {self.source_url}")
        if self.kind not in NO_QUOTE_NEEDED and not self.quote.strip():
            raise ValueError("an entry needs the quote that shows it on the official source")
        if self.checked_at.tzinfo is None:
            raise ValueError("checked_at must be timezone-aware")
        if self.region is None and self.kind in REGION_REQUIRED:
            raise ValueError(f"a {self.kind} needs a region")
        if self.region is not None and not known_region(self.region):
            raise ValueError(f"unknown region '{self.region}' (use a code of regions.yaml)")
        if self.kind in NAMES_A_LIST and not self.list_ids:
            raise ValueError(f"a {self.kind} names the official list it came from (R-32)")
        if self.kind in NEEDS_PARENT and not self.parent_id:
            raise ValueError(f"a {self.kind} needs a parent")
        if self.institution_type is not None and not _TYPE.match(self.institution_type):
            raise ValueError(f"institution type must be a snake case slug: {self.institution_type}")
        for d in self.official_domains:
            if not _DOMAIN.match(d):
                raise ValueError(f"official domain must be a bare domain like example.org: {d}")
