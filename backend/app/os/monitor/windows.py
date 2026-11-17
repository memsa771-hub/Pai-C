"""Notice windows (P2-D21): when a region's notices usually appear, per family. They are Knowledge facts of class
`notice_window` (scope `registry`, ref `<region>:<family>`, field `notice_window`, value `{opens: MM-DD, closes: MM-DD}`,
a window may wrap over the year end). Only a confirmed or verified window counts; with none, the region is off season and
only the TTL sweeper looks at its facts. A season is never invented."""

import logging
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Engine, select

from app.os import models

log = logging.getLogger(__name__)
K = models.knowledge_facts
FIELD = "notice_window"
_MD = re.compile(r"^(\d{2})-(\d{2})$")


@dataclass(frozen=True)
class Window:
    region: str
    family: str
    term: str  # the intake the notices are for
    year: int


def window_ref(region: str, family: str) -> str:
    return f"{region}:{family}"


def _md(text: object) -> tuple[int, int] | None:
    m = _MD.match(text) if isinstance(text, str) else None
    if m is None:
        return None
    month, day = int(m[1]), int(m[2])
    try:
        date(2000, month, day)  # a leap year, so 02-29 is allowed
    except ValueError:
        return None
    return month, day


def contains(value: object, today: date) -> bool | None:
    """Whether `today` is inside the window `value`; None if the value is not a window."""
    if not isinstance(value, dict):
        return None
    opens, closes = _md(value.get("opens")), _md(value.get("closes"))
    if opens is None or closes is None:
        return None
    here = (today.month, today.day)
    return opens <= here <= closes if opens <= closes else here >= opens or here <= closes


def active_windows(engine: Engine, tenant_id: str, today: date) -> list[Window]:
    """The windows `today` falls in, from confirmed or verified notice-window facts. A fact whose ref or value is
    malformed is ignored (and logged), never guessed."""
    with engine.connect() as conn:
        rows = conn.execute(select(K.c.id, K.c.ref, K.c.value, K.c.intake_term, K.c.intake_year).where(
            K.c.tenant_id == tenant_id, K.c.scope == "registry", K.c.field == FIELD,
            K.c.status.in_(("confirmed", "verified"))).order_by(K.c.id)).all()
    out: list[Window] = []
    for r in rows:
        region, sep, family = r.ref.partition(":")
        inside = contains(r.value, today)
        if not sep or not region or not family or inside is None:
            log.warning("notice window fact %s is malformed and ignored", r.id)
            continue
        if inside:
            out.append(Window(region, family, r.intake_term, r.intake_year))
    return sorted(set(out), key=lambda w: (w.region, w.family, w.year, w.term))
