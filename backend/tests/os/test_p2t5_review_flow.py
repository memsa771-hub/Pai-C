"""P2-T5: reviewers, the review queue, the two-person rule with independent AI checks, collection with evidence,
conflicts and attestation (R-25, R-42, R-72, R-75). Fictional values only."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.review import ReviewError, ReviewerError, ReviewerStore, ReviewQueue, load_policy

URL, QUOTE = "https://uni.test/apply", "Apply by 15 July 2027"
PNG = b"\x89PNG\r\n\x1a\n" + b"data"
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)
VALUE = {"date": "2027-07-15", "tz": "Europe/Berlin"}


class Setup:
    def __init__(self, engine):
        self.engine = engine
        self.kb = SqlKnowledge(engine, "pai")
        self.reviewers = ReviewerStore(engine, "pai")
        self.changes: list[tuple] = []
        self.q = self.queue()
        self.r = {}
        for ref, role, kind, ident in (("ai_check_1", "checker", "ai", "model-a/prompt-1"),
                                       ("ai_check_2", "approver", "ai", "model-b/prompt-2"),
                                       ("amina", "checker", "person", None), ("bilal", "approver", "person", None),
                                       ("owner", "admin", "person", None)):
            self.r[ref], _ = self.reviewers.add(ref, ref.title(), role, kind, identity=ident)

    def queue(self, policy=None) -> ReviewQueue:
        return ReviewQueue(self.engine, "pai", self.kb, policy=policy,
                           on_fact_change=lambda *a: self.changes.append(a))

    def fact(self, field="deadline_close", status="confirmed", value=None, read_method=None, ref="p1") -> int:
        sourced = status in ("confirmed", "verified")
        return self.kb.upsert("programme", ref, field, Fact(
            value if value is not None else VALUE, QUOTE if sourced or read_method else "",
            URL if sourced or read_method else "", AT, 2027, status, read_method=read_method))

    def status(self, fact_id) -> str:
        return self.kb.get(fact_id)[3].status


@pytest.fixture
def s(engine, clean):
    return Setup(engine)


def two_checks(s, item, fid):
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    return s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")


# --- reviewers ------------------------------------------------------------------------------------------------------

@pytest.mark.req("R-42")
def test_reviewer_token_is_shown_once_and_stored_hashed(s):
    r, token = s.reviewers.add("sana", "Sana", "checker")
    assert token.startswith("rvt_") and s.reviewers.authenticate(token) == r
    with s.engine.connect() as conn:
        stored = conn.execute(select(models.reviewers.c.token_hash).where(models.reviewers.c.ref == "sana")).scalar()
    assert stored != token and token not in stored
    assert s.reviewers.authenticate("rvt_wrong") is None and s.reviewers.authenticate(None) is None
    assert s.reviewers.authenticate("") is None


@pytest.mark.req("R-42")
def test_disable_rotate_and_refusals(s):
    r, token = s.reviewers.add("sana", "Sana", "checker")
    assert s.reviewers.set_active("sana", False) and s.reviewers.authenticate(token) is None
    assert s.reviewers.set_active("sana", True) and s.reviewers.authenticate(token) == r
    new = s.reviewers.rotate("sana")
    assert s.reviewers.authenticate(token) is None and s.reviewers.authenticate(new) == r
    assert s.reviewers.rotate("nobody") is None and not s.reviewers.set_active("nobody", False)
    for args in (("sana", "Again", "checker"), ("A B", "x", "checker"), ("zed", "x", "boss"), ("zed", "x", "checker", "bot"),
                 ("zed", " ", "checker")):
        with pytest.raises(ReviewerError):
            s.reviewers.add(*args)


# --- the two-person rule -----------------------------------------------------------------------------------------------

@pytest.mark.req("R-25")
@pytest.mark.req("R-42")
def test_high_stakes_fact_needs_a_check_and_an_approval(s):
    fid = s.fact()
    item, created = s.q.open_verify(fid)
    assert created
    r1 = s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    assert (r1["item_status"], r1["fact_status"]) == ("open", "confirmed")
    r2 = s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    assert (r2["item_status"], r2["resolution"], r2["fact_status"]) == ("closed", "verified", "verified")
    last = s.kb.revisions(fid)[-1]
    assert (last.action, last.cause, last.cause_ref, last.actor) == ("status", "review", str(item), "ai_check_2")
    assert last.before["status"] == "confirmed" and last.after["status"] == "verified"


@pytest.mark.req("R-25")
def test_other_facts_need_one_check(s):
    fid = s.fact("application_route", value="direct")
    item, _ = s.q.open_verify(fid)
    assert s.q.submit_review(item, s.r["amina"], "check", "correct")["fact_status"] == "verified"


@pytest.mark.req("R-42")
def test_one_reviewer_cannot_give_both_steps_or_wrong_role(s):
    item, _ = s.q.open_verify(s.fact())
    s.q.submit_review(item, s.r["owner"], "check", "correct")  # an admin may give either step
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(item, s.r["owner"], "approve", "approve")
    assert e.value.status == 409
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(item, s.r["ai_check_1"], "approve", "approve")  # a checker cannot approve
    assert e.value.status == 403
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(item, s.r["ai_check_2"], "check", "correct")  # an approver cannot check
    assert e.value.status == 403


@pytest.mark.req("R-42")
def test_a_reviewer_sees_no_other_review_before_giving_their_own_admins_too(s):
    item, _ = s.q.open_verify(s.fact())
    f = s.q.add_file(item, s.r["ai_check_1"], "n.png", "image/png", PNG)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct", note="matches the page")
    for who in ("ai_check_2", "owner"):  # an admin has no view into open reviews either
        before = s.q.detail(item, s.r[who])
        assert before["reviews"] == [] and before["my_review"] is None
        assert "matches the page" not in repr(before)
        assert [f["uploaded_by"] for f in before["files"]] == [None]  # who is reviewing is hidden too
    assert s.q.detail(item, s.r["ai_check_1"])["files"][0]["uploaded_by"] == "ai_check_1"
    with pytest.raises(ReviewError) as e:  # the admin-token view is not a way round the blindness
        s.q.audit(item)
    assert e.value.status == 409
    s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    audit = s.q.audit(item)
    assert [(r["reviewer"], r["identity"]) for r in audit["reviews"]] == [
        ("ai_check_1", "model-a/prompt-1"), ("ai_check_2", "model-b/prompt-2")]
    after = s.q.detail(item, s.r["ai_check_2"])
    assert [r["reviewer"] for r in after["reviews"]] == ["ai_check_1", "ai_check_2"]
    assert after["my_review"] == {"step": "approve", "outcome": "approve"}
    assert len(s.q.detail(item, s.r["owner"])["reviews"]) == 2  # closed: visible to all


@pytest.mark.req("R-42")
def test_policy_decides_which_reviewers_count(s):
    people_only = replace(load_policy(), counting_kinds=("person",))
    q = s.queue(people_only)
    item, _ = q.open_verify(s.fact())
    with pytest.raises(ReviewError) as e:
        q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    assert e.value.status == 403
    q.submit_review(item, s.r["amina"], "check", "correct")
    assert q.submit_review(item, s.r["bilal"], "approve", "approve")["fact_status"] == "verified"


@pytest.mark.req("R-42")
def test_min_persons_holds_back_two_ai_checks(s):
    q = s.queue(replace(load_policy(), min_persons=1))
    item, _ = q.open_verify(s.fact())
    q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    r = q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    assert (r["item_status"], r["fact_status"]) == ("open", "confirmed")
    # a person's check is added as a third review and the item can close
    r = q.submit_review(item, s.r["amina"], "check", "correct")
    assert (r["item_status"], r["fact_status"]) == ("closed", "verified")


# --- wrong, correct, reject, unclear -------------------------------------------------------------------------------------

@pytest.mark.req("R-25")
def test_wrong_check_moves_the_fact_down_and_tells_the_plans(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    with pytest.raises(ReviewError) as e:  # a note is required
        s.q.submit_review(item, s.r["ai_check_1"], "check", "wrong")
    assert e.value.status == 422
    r = s.q.submit_review(item, s.r["ai_check_1"], "check", "wrong", note="the page says 15 August")
    assert (r["resolution"], r["fact_status"]) == ("demoted", "unconfirmed")
    assert s.changes == [("programme", "p1", "deadline_close", fid, "unconfirmed", 2027, False)]
    assert "15 August" in s.kb.get(fid)[3].conflict_note


@pytest.mark.req("R-25")
def test_correction_keeps_the_old_state_and_needs_other_reviewers(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    new = {"date": "2027-08-15", "tz": "Europe/Berlin"}
    r = s.q.submit_review(item, s.r["ai_check_1"], "check", "wrong", corrected_value=new,
                          corrected_quote="Apply by 15 August 2027")
    assert r["resolution"] == "corrected" and r["fact_status"] == "unconfirmed"
    fact = s.kb.get(fid)[3]
    assert (fact.value, fact.quote, fact.read_method) == (new, "Apply by 15 August 2027", "human")
    old = s.kb.revisions(fid)[-1]
    assert old.before["value"] == VALUE and old.cause == "review" and old.actor == "ai_check_1"
    [nxt] = [i for i in s.q.list_items(kind="verify") if i.id != item]
    assert nxt.payload["author_ref"] == "ai_check_1"
    with pytest.raises(ReviewError) as e:  # the author cannot check their own reading
        s.q.submit_review(nxt.id, s.r["ai_check_1"], "check", "correct")
    assert e.value.status == 403
    s.q.submit_review(nxt.id, s.r["amina"], "check", "correct")  # compared with the original: confirmed
    assert s.status(fid) == "confirmed"
    assert s.changes[-1][4:] == ("confirmed", 2027, True)
    # that comparing check does not also count towards verified (M2): an approval alone is not enough
    assert s.q.submit_review(nxt.id, s.r["ai_check_2"], "approve", "approve")["fact_status"] == "confirmed"
    assert s.q.submit_review(nxt.id, s.r["owner"], "check", "correct")["fact_status"] == "verified"


@pytest.mark.req("R-75")
def test_reject_opens_a_conflict_item_and_keeps_the_fact(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    r = s.q.submit_review(item, s.r["ai_check_2"], "approve", "reject", note="the body's own page differs")
    assert (r["resolution"], r["fact_status"]) == ("rejected", "confirmed")
    [c] = s.q.list_items(kind="conflict")
    assert c.fact_id == fid and c.payload["source_item"] == item


@pytest.mark.req("R-72")
def test_unclear_opens_a_collect_item(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    r = s.q.submit_review(item, s.r["ai_check_1"], "check", "unclear", note="scan is blurred")
    assert r["resolution"] == "unclear"
    [c] = s.q.list_items(kind="collect")
    assert c.fact_id == fid and c.payload["reason"] == "unclear"


# --- collect with evidence -----------------------------------------------------------------------------------------------

@pytest.mark.req("R-72")
def test_collect_with_evidence_then_independent_checks(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "unclear", note="blurred")
    [c] = s.q.list_items(kind="collect")
    with pytest.raises(ReviewError) as e:  # evidence is required
        s.q.collect(c.id, s.r["amina"], value=VALUE, quote=QUOTE, url=URL)
    assert e.value.status == 422
    f = s.q.add_file(c.id, s.r["amina"], "../scan.png", "image/png", PNG)
    assert f["filename"] == "scan.png"
    out = s.q.collect(c.id, s.r["amina"], value=VALUE, quote=QUOTE, url=URL, evidence_file_id=f["id"])
    assert out["resolution"] == "collected" and s.status(fid) == "unconfirmed"
    assert s.kb.get(fid)[3].read_method == "human"
    nxt = out["verify_item_id"]
    with pytest.raises(ReviewError):
        s.q.submit_review(nxt, s.r["amina"], "check", "correct")  # the collector cannot check their own reading
    s.q.submit_review(nxt, s.r["ai_check_1"], "check", "correct")
    assert s.status(fid) == "confirmed"
    assert s.q.submit_review(nxt, s.r["bilal"], "approve", "approve")["fact_status"] == "confirmed"  # M2
    assert s.q.submit_review(nxt, s.r["owner"], "check", "correct")["fact_status"] == "verified"
    meta, data = s.q.get_file(f["id"])
    assert data == PNG and meta["content_type"] == "image/png"


@pytest.mark.req("R-72")
def test_collect_for_a_source_that_was_not_readable_creates_the_fact(s):
    item, created = s.q.open_item("collect", dedupe_key="collect:p9:deadline_close:2027", field="deadline_close",
                                  intake_year=2027, payload={"scope": "programme", "ref": "p9",
                                                             "reason": "not_readable"})
    assert created
    f = s.q.add_file(item, s.r["amina"], "notice.pdf", "application/pdf", b"%PDF-1.4")
    out = s.q.collect(item, s.r["amina"], value=VALUE, quote=QUOTE, url=URL, evidence_file_id=f["id"], note="scan")
    fid = out["fact_id"]
    scope, ref, field, fact = s.kb.get(fid)
    assert (scope, ref, field, fact.status, fact.read_method) == ("programme", "p9", "deadline_close", "unconfirmed",
                                                                  "human")
    assert [r.cause for r in s.kb.revisions(fid)] == ["review"]


@pytest.mark.req("R-72")
def test_evidence_limits_and_ownership(s):
    item, _ = s.q.open_item("collect", dedupe_key="c1", field="fee", intake_year=2027,
                            payload={"scope": "programme", "ref": "p9"})
    other, _ = s.q.open_item("collect", dedupe_key="c2", field="fee", intake_year=2027,
                             payload={"scope": "programme", "ref": "p8"})
    for ctype, data, code in (("application/x-msdownload", b"MZ\x90\x00\x03", 422), ("image/png", b"", 422),
                              ("text/plain", b"x" * (load_policy().evidence_max_bytes + 1), 413)):
        with pytest.raises(ReviewError) as e:
            s.q.add_file(item, s.r["amina"], "a", ctype, data)
        assert e.value.status == code
    f = s.q.add_file(other, s.r["amina"], "a.png", "image/png", PNG)
    with pytest.raises(ReviewError) as e:  # another item's file
        s.q.collect(item, s.r["amina"], value=1, quote="q", url=URL, evidence_file_id=f["id"])
    assert e.value.status == 422


@pytest.mark.req("R-72")
def test_the_server_decides_the_file_type_from_its_bytes(s):
    item, _ = s.q.open_item("collect", dedupe_key="c1", field="fee", intake_year=2027,
                            payload={"scope": "programme", "ref": "p9"})
    for name, ctype, data in (("a.html", "text/html", b"<script>alert(1)</script>"),
                              ("a.svg", "image/svg+xml", b"<svg onload=alert(1)/>"),
                              ("a.png", "image/png", b"<html><script>1</script></html>"),  # a lie about the type
                              ("a.png", "image/png", b"\x00\x01\x02 binary")):
        with pytest.raises(ReviewError) as e:
            s.q.add_file(item, s.r["amina"], name, ctype, data)
        assert e.value.status == 422, name
    assert "text/html" not in load_policy().evidence_types
    ok = s.q.add_file(item, s.r["amina"], "a.txt", "", b"Notice: fee is 100")  # no claim: the bytes decide
    assert ok["content_type"] == "text/plain"
    pdf = s.q.add_file(item, s.r["amina"], "a.pdf", "application/octet-stream", b"%PDF-1.7 ...")
    assert pdf["content_type"] == "application/pdf"


@pytest.mark.req("R-72")
def test_a_collected_source_must_be_a_web_address(s):
    item, _ = s.q.open_item("collect", dedupe_key="c1", field="fee", intake_year=2027,
                            payload={"scope": "programme", "ref": "p9"})
    f = s.q.add_file(item, s.r["amina"], "a.png", "image/png", PNG)
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x.test/a", "uni.test/apply", "https://"):
        with pytest.raises(ReviewError) as e:
            s.q.collect(item, s.r["amina"], value=1, quote="q", url=bad, evidence_file_id=f["id"])
        assert e.value.status == 422, bad


# --- changes under review, items, attestation ------------------------------------------------------------------------------

@pytest.mark.req("R-25")
def test_a_changed_fact_voids_its_open_item_at_the_moment_of_the_change(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    s.kb.revise(fid, value={"date": "2027-09-01"}, quote="Apply by 1 September 2027", cause="research")
    closed = s.q.get_item(item)
    assert (closed.status, closed.resolution) == ("closed", "void")  # no waiting for the next review to notice
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    assert e.value.status == 409
    [fresh] = [i for i in s.q.list_items(kind="verify") if i.id != item]  # the writer opened the replacement
    assert fresh.fact_id == fid and s.q.sync() == 0


@pytest.mark.req("R-25")
@pytest.mark.parametrize("change", [{"fact_class": "fee"}, {"read_method": "ocr"}, {"url": "https://uni.test/other"}])
def test_every_part_of_the_reading_voids_the_item(s, change):
    """The digest covers value, quote, URL, class and how it was read (I4)."""
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.kb.upsert("programme", "p1", "deadline_close", Fact(
        VALUE, QUOTE, change.get("url", URL), AT, 2027, "confirmed", fact_class=change.get("fact_class"),
        read_method=change.get("read_method")))
    assert s.q.get_item(item).resolution == "void"


@pytest.mark.req("R-25")
def test_an_item_a_writer_skipped_while_locked_is_voided_by_its_digest(s, monkeypatch):
    """Another writer changes the reading while the review holds the item locked, so the store's void skips the item
    (SKIP LOCKED). The review works on the locked fact row, sees the new reading in the digest check, voids the item
    and verifies nothing."""
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    real = s.kb.locked
    done = []

    def racing(conn, fact_id):
        if not done:  # the writer commits before our lock is taken
            done.append(1)
            s.kb.revise(fact_id, value={"date": "2027-10-01"}, quote="Apply by 1 October 2027", cause="research",
                        status="confirmed")
        return real(conn, fact_id)

    monkeypatch.setattr(s.kb, "locked", racing)
    r = s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    assert (r["item_status"], r["resolution"], r["fact_status"]) == ("closed", "void", "confirmed")
    assert s.kb.get(fid)[3].value == {"date": "2027-10-01"}


def test_set_status_and_revise_check_the_digest_on_the_locked_row(s):
    from app.os.knowledge.store import StaleFact, fact_digest

    fid = s.fact()
    good = fact_digest(s.kb.get(fid)[3])
    s.kb.revise(fid, value={"date": "2027-10-01"}, quote="Apply by 1 October 2027", cause="research", status="confirmed")
    with pytest.raises(StaleFact):
        s.kb.set_status(fid, "verified", cause="review", expected_digest=good)
    with pytest.raises(StaleFact):
        s.kb.revise(fid, status="unconfirmed", cause="review", expected_digest=good)
    assert s.status(fid) == "confirmed"
    s.kb.set_status(fid, "verified", cause="review", expected_digest=fact_digest(s.kb.get(fid)[3]))


@pytest.mark.req("R-42")
def test_two_checks_need_two_distinct_identities(s):
    """M1: two refs that are one model (or one person) are not two checks."""
    twin, _ = s.reviewers.add("ai_check_3", "AI check 3", "approver", "ai", identity="  MODEL-A/Prompt-1 ")
    item, _ = s.q.open_verify(s.fact())
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(item, twin, "approve", "approve")
    assert e.value.status == 409 and "identit" in e.value.detail
    assert s.q.get_item(item).status == "open"
    s.q.submit_review(item, s.r["ai_check_2"], "approve", "approve")
    assert s.q.get_item(item).resolution == "verified"
    assert twin.identity == "model-a/prompt-1"  # stripped and case-folded
    assert s.reviewers.add("x1", "X", "checker")[0].identity == "x1"  # default: the ref
    with pytest.raises(ReviewerError):  # an AI reviewer must name the model and prompt behind it
        s.reviewers.add("ai_check_4", "AI 4", "checker", "ai")


@pytest.mark.req("R-25")
def test_the_high_stakes_need_is_recorded_with_the_review(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    with s.engine.connect() as conn:
        assert conn.execute(select(models.fact_reviews.c.high_stakes)).scalar() is True
    s.kb.revise(fid, status="unconfirmed", conflict_note="x", cause="manual")  # unrelated, same reading
    assert s.q.get_item(item).status == "open"


@pytest.mark.req("R-25")
def test_evaluate_can_be_run_again(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    two_checks(s, item, fid)
    again = s.q.evaluate(item)
    assert (again["item_status"], again["resolution"]) == ("closed", "verified")
    assert [r.action for r in s.kb.revisions(fid)].count("status") == 1


@pytest.mark.req("R-25")
def test_stale_or_unconfirmed_facts_are_not_checked(s):
    for status in ("stale", "unconfirmed"):
        fid = s.fact("fee_x" + status, status=status if status == "unconfirmed" else "confirmed")
        item, _ = s.q.open_item("verify", dedupe_key=f"v:{fid}", fact_id=fid)
        if status == "stale":
            s.kb.mark_stale(fid)
        with pytest.raises(ReviewError) as e:
            s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
        assert e.value.status == 409


@pytest.mark.req("R-42")
def test_the_same_thing_opened_again_joins_the_item(s):
    fid = s.fact()
    a, created = s.q.open_item("report", dedupe_key=f"report:{fid}", fact_id=fid, opened_by="report")
    b, again = s.q.open_item("report", dedupe_key=f"report:{fid}", fact_id=fid, opened_by="report")
    assert (a == b, created, again) == (True, True, False)
    assert s.q.get_item(a).join_count == 1
    s.q.resolve(a, s.r["amina"], "resolved", "looked at the page")
    c, fresh = s.q.open_item("report", dedupe_key=f"report:{fid}", fact_id=fid, opened_by="report")
    assert fresh and c != a  # once closed, a new report is a new item


@pytest.mark.req("R-42")
def test_sync_opens_verify_items_for_confirmed_high_stakes_facts_only(s):
    hi = s.fact()
    s.fact("application_route", value="direct")
    s.fact("fee", status="unconfirmed", value=1)
    assert s.q.sync() == 1 and s.q.sync() == 0
    assert [i.fact_id for i in s.q.list_items(kind="verify")] == [hi]
    assert s.q.sync(high_stakes_only=False, batch_ref="b2") == 1


@pytest.mark.req("R-42")
def test_resolve_needs_a_note_and_never_closes_a_verify_item(s):
    item, _ = s.q.open_item("suspect_domain", dedupe_key="sd:x.test", subject="x.test")
    with pytest.raises(ReviewError):
        s.q.resolve(item, s.r["amina"], "resolved", " ")
    s.q.resolve(item, s.r["amina"], "dismissed", "a known mirror")
    assert s.q.get_item(item).payload["resolution_note"] == "a known mirror"
    v, _ = s.q.open_verify(s.fact())
    with pytest.raises(ReviewError):
        s.q.resolve(v, s.r["amina"], "resolved", "x")
    with pytest.raises(ReviewError):
        s.q.resolve(item, s.r["amina"], "resolved", "again")  # closed


@pytest.mark.req("R-42")
def test_attestation_is_once_per_reviewer_and_batch(s):
    assert s.q.attest(s.r["amina"], "b3") is True and s.q.attest(s.r["amina"], "b3") is False
    assert s.q.attested("amina", "b3") and not s.q.attested("amina", "b4") and not s.q.attested("bilal", "b3")
    s.reviewers.set_active("amina", False)
    assert not s.q.attested("amina", "b3")


@pytest.mark.req("R-25")
def test_revise_cannot_set_verified_and_a_changed_verified_reading_drops(s):
    fid = s.fact()
    with pytest.raises(ValueError):
        s.kb.revise(fid, status="verified", cause="review")
    item, _ = s.q.open_verify(fid)
    two_checks(s, item, fid)
    assert s.status(fid) == "verified"
    s.kb.revise(fid, value={"date": "2027-09-01"}, quote="Apply by 1 September 2027", cause="research")
    assert s.status(fid) == "unconfirmed" and s.kb.revisions(fid)[-1].before["status"] == "verified"


@pytest.mark.req("R-25")
def test_a_replacement_item_keeps_the_author_bar_and_the_batch(s):
    fid = s.fact()
    item, _ = s.q.open_item("verify", dedupe_key=f"verify:{fid}", fact_id=fid, batch_ref="b7",
                            payload={"author_ref": "amina"})
    s.kb.revise(fid, value={"date": "2027-09-01"}, quote="Apply by 1 September 2027", cause="research")
    [fresh] = [i for i in s.q.list_items(kind="verify") if i.id != item]
    assert (fresh.batch_ref, fresh.payload.get("author_ref")) == ("b7", "amina")
    with pytest.raises(ReviewError) as e:
        s.q.submit_review(fresh.id, s.r["amina"], "check", "correct")
    assert e.value.status == 403


@pytest.mark.req("R-25")
def test_no_replacement_when_the_fact_can_no_longer_be_checked(s):
    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.kb.revise(fid, value={"date": "2027-09-01"}, quote="Apply by 1 September 2027", status="unconfirmed",
                cause="research")
    assert s.q.get_item(item).resolution == "void" and s.q.list_items(kind="verify") == []


@pytest.mark.req("R-25")
def test_joining_an_item_a_writer_skipped_voids_it(s, engine):
    """The SKIP LOCKED gap: the writer skipped a locked item. The next open_item that joins it re-runs the check."""
    from sqlalchemy import update

    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    with engine.begin() as conn:  # the content changes but the writer did not void the item (it was locked)
        conn.execute(update(models.knowledge_facts).where(models.knowledge_facts.c.id == fid)
                     .values(quote="Apply by 1 September 2027"))
    again, created = s.q.open_verify(fid)
    assert s.q.get_item(item).resolution == "void" and not created
    s.q.sync()
    [fresh] = s.q.list_items(kind="verify")
    assert fresh.id != item


@pytest.mark.req("R-25")
def test_sync_sweeps_stale_items_and_includes_readings_waiting_for_comparison(s, engine):
    from sqlalchemy import update

    fid = s.fact()
    item, _ = s.q.open_verify(fid)
    s.q.submit_review(item, s.r["ai_check_1"], "check", "correct")
    with engine.begin() as conn:
        conn.execute(update(models.knowledge_facts).where(models.knowledge_facts.c.id == fid)
                     .values(quote="Apply by 1 September 2027"))
    ocr = s.fact("fee", status="unconfirmed", value=100, read_method="ocr", ref="p2")
    assert s.q.sync() == 2  # a fresh item for the changed reading, and one for the OCR reading
    assert s.q.get_item(item).resolution == "void"
    assert {i.fact_id for i in s.q.list_items(kind="verify")} == {fid, ocr}
