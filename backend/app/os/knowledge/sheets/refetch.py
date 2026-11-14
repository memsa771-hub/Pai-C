"""Re-fetch a row's source and match its quote word for word (P2 spec P2-D18; master R-68, R-72). A row read by a model or
from an image cannot be `confirmed` before this matches; an unconfirmed row with a quote is promoted when it does."""

from dataclasses import dataclass

from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import quote_on_page
from app.os.knowledge.sheets.plan import Scope
from app.os.knowledge.sheets.ports import Fetcher


@dataclass(frozen=True)
class Outcome:
    matched: bool
    reason: str  # quote_matched | quote_not_found | refetch_blocked:<why> | refetch_not_run


class Refetcher:
    """One fetch per URL and scope per import. `fetch` is `PageGateway.fetch(url, own, shared, scope)`: the page is read
    only when the domain is official for the scope (the allow-list, T3), otherwise it comes back blocked."""

    def __init__(self, fetcher: Fetcher | None, family: str = "") -> None:
        self.fetcher, self.family = fetcher, family
        self._pages: dict[tuple[str, str, str], tuple[str, str | None]] = {}

    def _page(self, url: str, region: str, family: str) -> tuple[str, str | None]:
        key = (url, region, family)
        if key not in self._pages:
            try:
                page = self.fetcher.fetch(url, (), (), Scope(region=region, family=family))
                self._pages[key] = (normalise(page.text or ""), page.blocked)
            except Exception as e:  # noqa: BLE001  (a transient failure is not a mismatch)
                self._pages[key] = ("", f"error:{type(e).__name__}")
        return self._pages[key]

    def check(self, url: str, quote: str, region: str | None, families: tuple[str, ...] | None = None) -> Outcome:
        """`families`: the allow-list families the row may be read for (the plan's, P2-T19), tried in order until the
        page is not blocked; None: the run's `--family`."""
        if self.fetcher is None:
            return Outcome(False, "refetch_not_run")
        text, blocked = "", None
        for family in families or (self.family,):
            text, blocked = self._page(url, region or "", family)
            if not blocked:
                break
        if blocked:
            return Outcome(False, f"refetch_blocked:{blocked}")
        return Outcome(quote_on_page(quote, text), "quote_matched" if quote_on_page(quote, text) else "quote_not_found")
