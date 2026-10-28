"""The short rehearsal in CI (Slice 9a spec §2.4 "CI"): S1, S3 and S5, offline, end to end, on a real worker process.

S1 has no event; S3 is "Not admitted" by one programme and accepts the suggestion that removes it; S5 never uploads
one document until a support case is opened. Each must reach both end points (ready to submit, visa file ready), each
scripted event must give its change, and the failure log must be empty. The full 12 and the kill run are run by hand
(`python -m tests.os.rehearsal.run`). Fictional data only.

Strict xfail (plan ruling 4): the run finds two product failures, named in KNOWN and in the reason. Only exactly
that set raises KnownProductFailures, the one exception the mark expects: a failed end point or event, a new failure,
or one of the two fixed without the other fails the suite as usual, and so does a pass (XPASS, strict) once Task 11 has
fixed both, so the mark is then removed and KNOWN emptied."""

import pytest

from tests.os.rehearsal.driver import Rehearsal
from tests.os.rehearsal.failures import FailureLog

STUDENTS = ["S1", "S3", "S5"]
KNOWN = {"fact_missing:visa_target_date", "left_open:S3:removed_programme"}  # Task 11 fixes these (or owners accept)


class KnownProductFailures(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=KnownProductFailures,
                   reason="product failures fact_missing:visa_target_date, left_open:S3:removed_programme (Task 11)")
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

    ids = {f.id for f in failures}
    assert ids in (set(), KNOWN), sorted(ids)  # a new failure, or a partial fix in Task 11, fails the suite
    if ids:
        raise KnownProductFailures([f"{f.id}: {f.got}" for f in failures])
    assert report.failures == {}
