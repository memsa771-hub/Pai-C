"""The shared clock (Slice 9a): real UTC time unless an offset reader is installed."""

from datetime import datetime, timedelta, timezone

from app.os import clock


def test_now_is_aware_utc():
    assert clock.now().tzinfo is timezone.utc


def test_configured_offset_moves_now_and_today():
    clock.configure(lambda: timedelta(days=40))
    try:
        assert clock.now() - datetime.now(timezone.utc) > timedelta(days=39, hours=23)
        assert clock.today() == clock.now().date()
    finally:
        clock.configure(None)


def test_a_default_bound_to_clock_now_sees_a_later_configure():
    def uses_default(read=clock.now):
        return read()

    clock.configure(lambda: timedelta(days=10))
    try:
        assert uses_default() - datetime.now(timezone.utc) > timedelta(days=9)
    finally:
        clock.configure(None)
    assert uses_default() - datetime.now(timezone.utc) < timedelta(seconds=5)
