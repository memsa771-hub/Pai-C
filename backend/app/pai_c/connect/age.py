"""Age on the day of the choice (D-i, R-10). Whether a student is under 18 decides if a guardian must agree."""

import calendar
import re
from datetime import date

_DOB = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
ADULT = 18


def _adult_from(day: date) -> date:
    try:
        return day.replace(year=day.year + ADULT)
    except ValueError:  # 29 February: the first day of March is the safe side
        return date(day.year + ADULT, 3, 1)


def under_18(dob: str | None, on: date) -> bool | None:
    """True when the student is under 18 on `on`, False when 18 or over, None when there is no date of birth.

    The date is `YYYY`, `YYYY-MM` or `YYYY-MM-DD`. A partial date counts from its latest possible day: if that
    cannot prove 18 or over, the student counts as under 18. A date that cannot be read counts as no date."""
    match = _DOB.match((dob or "").strip())
    if match is None:
        return None
    year, month, day = (int(part) if part else None for part in match.groups())
    try:
        if month is None:
            latest = date(year, 12, 31)
        elif day is None:
            latest = date(year, month, calendar.monthrange(year, month)[1])
        else:
            latest = date(year, month, day)
    except ValueError:
        return None
    try:
        return _adult_from(latest) > on
    except ValueError:  # a year so late that 18 more years do not exist
        return True
