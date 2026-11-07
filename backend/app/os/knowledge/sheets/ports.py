"""What the import needs from other tasks' code, as narrow protocols (T3 sources, T5 review queue). The real objects
(`PageGateway`, `SourceDomains`, `ReviewQueue`) fit them; tests use fakes."""

from collections.abc import Sequence
from typing import Any, Protocol


class PageLike(Protocol):
    text: str
    blocked: str | None


class Fetcher(Protocol):
    def fetch(self, url: str, own_domains: Sequence[str], shared_domains: Sequence[str],
              scope: Any = None) -> PageLike: ...


class Disputes(Protocol):
    def open_item(self, kind: str, *, dedupe_key: str, fact_id: int | None = None, subject: str = "",
                  field: str | None = None, intake_term: str = "", intake_year: int | None = None, owner_ref: str = "",
                  summary: str = "", payload: dict | None = None, batch_ref: str | None = None,
                  opened_by: str = "manual") -> tuple[int, bool]: ...
