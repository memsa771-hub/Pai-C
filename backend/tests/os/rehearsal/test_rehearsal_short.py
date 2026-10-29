"""The short rehearsal in CI (Slice 9a spec §2.4 "CI"): S1, S3 and S5, offline, end to end, on a real worker process.

S1 has no event; S3 is "Not admitted" by one programme and accepts the suggestion that removes it; S5 never uploads
one document until a support case is opened. Each must reach both end points (ready to submit, visa file ready), each
scripted event must give its change, and the failure log must be empty. The full 12 and the kill run are run by hand
(`python -m tests.os.rehearsal.run`). Fictional data only.

No xfail (Task 11): batch A fixed `left_open:S3:removed_programme`, and batch C fixed `fact_missing:visa_target_date`
(F1: the visa date is derived from the visa programme's semester start; the rehearsal loads fictional semester starts as
test data). Any failure in the log fails the test."""

from tests.os.rehearsal.driver import Rehearsal
from tests.os.rehearsal.failures import FailureLog

STUDENTS = ["S1", "S3", "S5"]


def test_rehearsal_short(os_db, tmp_path):
    report = Rehearsal(STUDENTS, tmp_path / "run").run()
    failures = FailureLog(tmp_path / "run" / "failures.yaml").entries()

    for sid in STUDENTS:
        got = report.students[sid]
        assert got.state == "visa_ready", (sid, got, failures)
        assert got.reached == ["ready_to_submit", "visa_ready"], (sid, got)
    assert "rejected:ok" in report.students["S3"].events  # the programme is removed (or swapped)
    assert "missing_document:ok" in report.students["S5"].events  # reminders, an ask, then a support case
    assert (tmp_path / "run" / "report.json").is_file() and (tmp_path / "run" / "report.md").is_file()

    assert [f"{f.id}: {f.got}" for f in failures] == []
    assert report.failures == {}
