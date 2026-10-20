"""Programme registry (Slice 2 spec §4.1): the programmes research reads, with their start pages and domains."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert

from app.os import models

T = models.programmes
PROGRAMME_SEED = Path(__file__).parent / "seed" / "programmes_germany.yaml"
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


class ProgrammeSeedError(ValueError):
    pass


@dataclass(frozen=True)
class Programme:
    ref: str
    route_key: str
    university: str
    name: str
    aliases: tuple[str, ...]
    start_urls: tuple[str, ...]
    official_domains: tuple[str, ...]  # the university's own; the route's shared sources are in its profile
    status: Literal["active", "excluded"] = "active"
    notes: str | None = None
    # Start URLs no other programme of the tenant uses: pages about this programme (the trust rules' scope
    # check). Filled by `with_own_pages` / the store; a shared start page (a university-wide page) is not one.
    own_pages: tuple[str, ...] = ()


def with_own_pages(programmes: list[Programme]) -> list[Programme]:
    """Each programme with `own_pages`: its start URLs that appear in no other programme's start URLs."""
    from collections import Counter
    from dataclasses import replace

    uses = Counter(u for p in programmes for u in set(p.start_urls))
    return [replace(p, own_pages=tuple(u for u in p.start_urls if uses[u] == 1)) for p in programmes]


class _SeedProgramme(BaseModel):
    model_config = ConfigDict(extra="forbid")
    university: str
    name: str
    aliases: list[str] = []
    start_urls: list[str]
    official_domains: list[str]
    status: Literal["active", "excluded"] = "active"
    notes: str | None = None

    @field_validator("start_urls")
    @classmethod
    def _https(cls, urls: list[str]) -> list[str]:
        for url in urls:
            if not url.startswith("https://"):
                raise ValueError(f"start URL must use https: {url}")
        return urls

    @field_validator("official_domains")
    @classmethod
    def _bare(cls, domains: list[str]) -> list[str]:
        for domain in domains:
            if not _DOMAIN.match(domain):
                raise ValueError(f"official domain must be a bare domain like example.org: {domain}")
        return domains


class _Seed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    route_key: str
    programmes: dict[str, _SeedProgramme]


def _programme(row) -> Programme:
    return Programme(ref=row.ref, route_key=row.route_key, university=row.university, name=row.name,
                     aliases=tuple(row.aliases), start_urls=tuple(row.start_urls),
                     official_domains=tuple(row.official_domains), status=row.status, notes=row.notes)


class ProgrammeStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def upsert(self, p: Programme) -> int:
        values = {"route_key": p.route_key, "university": p.university, "name": p.name,
                  "aliases": list(p.aliases), "start_urls": list(p.start_urls),
                  "official_domains": list(p.official_domains), "status": p.status, "notes": p.notes}
        stmt = insert(T).values(tenant_id=self.tenant_id, ref=p.ref, **values).on_conflict_do_update(
            constraint="uq_os_programmes_ref", set_={**values, "updated_at": func.now()}).returning(T.c.id)
        with self.engine.begin() as conn:
            return conn.execute(stmt).scalar_one()

    def _all(self) -> list[Programme]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(T).where(T.c.tenant_id == self.tenant_id).order_by(T.c.ref)).all()
        return with_own_pages([_programme(r) for r in rows])

    def get(self, ref: str) -> Programme | None:
        """The programme with its own pages (start URLs no other programme of the tenant uses)."""
        return next((p for p in self._all() if p.ref == ref), None)

    def active(self, route_key: str) -> list[Programme]:
        return [p for p in self._all() if p.route_key == route_key and p.status == "active"]


def load_programme_seed(path: Path, store: ProgrammeStore | None) -> int:
    """Insert-or-update every programme in the seed. Validates the whole file before writing anything.

    It never touches facts (handoff M6). Returns the number of programmes.
    """
    try:
        seed = _Seed.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as e:
        raise ProgrammeSeedError(f"{path.name}: {e}") from e
    if store is not None:
        for ref, p in seed.programmes.items():
            store.upsert(Programme(ref=ref, route_key=seed.route_key, university=p.university, name=p.name,
                                   aliases=tuple(p.aliases), start_urls=tuple(p.start_urls),
                                   official_domains=tuple(p.official_domains), status=p.status, notes=p.notes))
    return len(seed.programmes)
