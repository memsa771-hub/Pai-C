"""Local schedule and daylight-saving behavior for application reviews."""
from datetime import datetime, timezone

from app.routers.routines import _compute_next_fires_at


def test_daily_review_uses_student_timezone():
    now = datetime(2027, 1, 10, 0, 0, tzinfo=timezone.utc)
    fire = _compute_next_fires_at(9, 0, None, None, "Asia/Karachi", now)
    assert fire == datetime(2027, 1, 10, 4, 0, tzinfo=timezone.utc)


def test_nonexistent_spring_forward_time_is_skipped():
    # 02:30 in New York does not exist when clocks advance on this Sunday.
    now = datetime(2027, 3, 14, 5, 0, tzinfo=timezone.utc)
    fire = _compute_next_fires_at(2, 30, [6], None, "America/New_York", now)
    assert fire == datetime(2027, 3, 21, 6, 30, tzinfo=timezone.utc)


def test_ambiguous_fall_back_time_chooses_first_future_occurrence():
    now = datetime(2027, 11, 7, 4, 0, tzinfo=timezone.utc)
    fire = _compute_next_fires_at(1, 30, [6], None, "America/New_York", now)
    assert fire == datetime(2027, 11, 7, 5, 30, tzinfo=timezone.utc)
