"""The one clock for the OS. Real UTC time unless rehearsal mode installs an offset reader (Slice 9a).

Stdlib only, so any app/os module can import it. `now` and `today` read the offset at call time, so a default
bound as `clock=clock.now` still sees a later `configure(...)`."""

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

_offset: Callable[[], timedelta] | None = None


def configure(offset: Callable[[], timedelta] | None) -> None:
    """Install a reader that says how far the clock is moved; None means real time."""
    global _offset
    _offset = offset


def now() -> datetime:
    moved = datetime.now(timezone.utc)
    return moved + _offset() if _offset is not None else moved


def today() -> date:
    return now().date()
