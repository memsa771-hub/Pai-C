"""P2-T3: page snapshots and original files (R-29, snapshot part)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.os.knowledge.sources.snapshots import SnapshotError, SnapshotStore, text_hash

pytestmark = pytest.mark.req("R-29")
T0 = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


def test_save_latest_and_dedupe(engine, clean):
    s = SnapshotStore(engine, "pai")
    a = s.save("https://x.test/p", "one  two\nthree", content_type="text/html", fetched_at=T0)
    assert a.sha256 == text_hash("one two three") and a.read_method == "fetch"
    b = s.save("https://x.test/p", "different", fetched_at=T0 + timedelta(hours=1), flagged="spam")
    again = s.save("https://x.test/p", "one two three", fetched_at=T0 + timedelta(hours=2))
    assert again.id == a.id and again.fetched_at == T0 + timedelta(hours=2)
    assert s.latest("https://x.test/p").id == a.id
    assert s.latest("https://x.test/p", clean_only=False).id == a.id  # a was read last
    assert s.get(b.id).flagged == "spam"
    assert s.latest("https://x.test/none") is None


def test_flagged_snapshots_are_never_the_last_clean_one(engine, clean):
    s = SnapshotStore(engine, "pai")
    clean_snap = s.save("https://x.test/p", "good", fetched_at=T0)
    s.save("https://x.test/p", "casino betting", fetched_at=T0 + timedelta(hours=1), flagged="spam")
    assert s.latest("https://x.test/p").id == clean_snap.id


def test_original_bytes_for_pdf_and_images_only_with_a_cap(engine, clean):
    s = SnapshotStore(engine, "pai", max_bytes=10)
    snap = s.save("https://x.test/a.pdf", "text", content_type="application/pdf", original=b"%PDF-1", 
                  original_type="application/pdf")
    assert s.original(snap.id) == (b"%PDF-1", "application/pdf")
    with pytest.raises(SnapshotError):
        s.save("https://x.test/b.png", "t", original=b"x" * 11, original_type="image/png")
    with pytest.raises(SnapshotError):
        s.save("https://x.test/c", "t", original=b"x", original_type="text/html")
    assert s.original(10**6) is None
    with pytest.raises(Exception):
        s.save("https://x.test/d", "t", read_method="guess")
