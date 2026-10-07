"""The billed evaluation leaves a reviewable report even when a run fails."""

from scripts.eval_counselor_sim import report


def test_report_groups_checks_and_preserves_error_transcript(tmp_path):
    results = [{
        "persona": "sample", "mode": "chat", "run": 0,
        "checks": {"turns": 1, "error": 1},
        "judge": {"natural": False}, "error": "turn 1: ValueError: empty extraction",
        "transcript": [{"role": "student", "text": "hello"}],
    }]
    path = tmp_path / "eval.md"
    report(results, path)
    content = path.read_text(encoding="utf-8")
    assert "Pass rate by persona" in content
    assert "0/1" in content
    assert "turn 1: ValueError: empty extraction" in content
    assert "### not_queued" in content
    assert "- student: hello" in content
