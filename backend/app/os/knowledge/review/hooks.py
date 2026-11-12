"""Wiring between the review queue and the source guard (integration of P2-T3 and P2-T5)."""

from app.os.knowledge.review.queue import ReviewQueue
from app.os.knowledge.sources.suspect import SuspectCase


def open_suspect_item(queue: ReviewQueue):
    """The `SourceGuard.on_suspect` hook: a domain that went suspect becomes a `suspect_domain` review item, once. The
    item names the domain, why, the page, the snapshot to look at and the facts that were dropped."""
    def hook(case: SuspectCase) -> None:
        queue.open_item(
            "suspect_domain", dedupe_key=f"suspect_domain:{case.domain}", subject=case.domain,
            summary=f"{case.domain} was set aside: {case.reason}",
            payload={"reason": case.reason, "detail": case.detail, "url": case.url, "snapshot_id": case.snapshot_id,
                     "facts_dropped": list(case.facts_dropped)},
            opened_by="monitor")
    return hook
