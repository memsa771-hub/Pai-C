"""P1-T10 Task B1 (R-04): every P1 row of master section 6 has a scripted test, and no test claims a row P1 does not
test. A test says which rows it proves with `@pytest.mark.connect_row("6.1", ...)`. The marks are read from the source
(no import, no database), so this runs in every job.

P1 rows: 6.1-6.9, 6.11-6.19, 6.21, 6.22. Not P1: 6.10 (Knowledge changes), 6.20 (the result-expected step is only
exercised as a mechanism inside the T8 flow), 6.23-6.25 (later phases). `EXISTING` lists the rows the earlier flows
prove until B2 puts the marks on those flows; each node must still exist."""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-04")

ROOT = Path(__file__).parent
P1_ROWS = {f"6.{n}" for n in (*range(1, 10), *range(11, 20), 21, 22)}
NOT_P1 = {"6.10", "6.20", "6.23", "6.24", "6.25"}

# rows proved by flows written before the marker existed: row -> test nodes (B2 replaces this with marks)
EXISTING = {
    "6.1": ["test_connect_t5_flow.py::test_germany_route"],
    "6.2": ["test_connect_t5_flow.py::test_germany_route"],
    "6.4": ["test_connect_t5_flow.py::test_germany_route",
            "test_connect_t3_flow.py::test_an_adult_chooses_withdraws_and_gives_consent_again"],
    "6.5": ["test_connect_t6_flow.py::test_6_5_6_6_a_vault_drop_ends_in_a_request_and_version_2_both_sides"],
    "6.6": ["test_connect_t6_flow.py::test_6_5_6_6_a_vault_drop_ends_in_a_request_and_version_2_both_sides"],
    "6.7": ["test_connect_t7_flow.py::test_germany_transcript_from_upload_to_replan"],
    "6.8": ["test_connect_t4_flow.py::test_a_vault_write_that_drops_marks_ends_in_a_pending_big_proposal"],
    "6.11": ["test_connect_t5_flow.py::test_germany_route"],
    "6.12": ["test_connect_t6_flow.py::test_6_12_all_rejected_pauses_the_plan_and_a_new_choice_resumes_it"],
    "6.13": ["test_connect_t6_flow.py::test_6_13_the_builder_with_the_counsellor_on_writes_the_next_version"],
    "6.14": ["test_connect_t3_flow.py::test_a_route_the_os_cannot_run_puts_nothing_in_the_os",
             "test_connect_t5_flow.py::test_a_route_the_os_cannot_run_keeps_the_labelled_checklist"],
    "6.15": [("test_connect_t3_flow.py::test_an_under_18_student_is_held_until_the_guardian_agrees_and_paused_when_"
              "the_guardian_withdraws")],
    "6.16": ["test_connect_t6_flow.py::test_6_16_a_self_serve_plan_is_adopted_when_the_student_agrees"],
    "6.17": ["test_connect_t6_flow.py::test_6_17_with_the_module_off_the_plans_stay_standalone_and_accept_edits_directly"],
    "6.19": ["test_connect_t8_flow.py::test_6_19_germany_v2_asks_for_the_certificates_and_blocks_the_applications"],
    "6.21": ["test_connect_t8_flow.py::test_6_21_germany_the_two_values_are_shown_and_the_answer_goes_to_the_vault"],
    "6.22": ["test_connect_t8_flow.py::test_6_22_ireland_the_ladder_reminders_at_risk_proposal_and_a_support_case"],
}


def _marks(node) -> set[str]:
    """The rows named by `connect_row(...)` in a decorator list or a `pytestmark` value."""
    found = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", None) == "connect_row":
            found |= {a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return found


def marked() -> dict[str, list[str]]:
    """Row -> the `file::test` nodes that carry the mark, across tests/os and tests."""
    rows: dict[str, list[str]] = {}
    for path in sorted([*ROOT.glob("test_*.py"), *ROOT.parent.glob("test_*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        module = set()
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in stmt.targets):
                module = _marks(stmt.value)
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name.startswith("test"):
                for row in module | {r for d in fn.decorator_list for r in _marks(d)}:
                    rows.setdefault(row, []).append(f"{path.name}::{fn.name}")
    return rows


def node_exists(node: str) -> bool:
    name, _, test = node.partition("::")
    tree = ast.parse((ROOT / name).read_text(encoding="utf-8-sig"))
    return any(isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == test for f in ast.walk(tree))


def test_every_p1_row_of_master_section_6_has_a_test():
    have = marked()
    missing = sorted(r for r in P1_ROWS if not have.get(r) and not EXISTING.get(r))
    assert missing == [], f"rows without a test: {missing}"


def test_no_test_claims_a_row_p1_does_not_test():
    assert sorted(set(marked()) - P1_ROWS) == []
    assert sorted(set(EXISTING) - P1_ROWS) == [] and not NOT_P1 & set(marked())


def test_every_listed_existing_node_still_exists():
    gone = [n for nodes in EXISTING.values() for n in nodes if not node_exists(n)]
    assert gone == [], f"listed tests that no longer exist: {gone}"


def test_the_new_row_tests_are_the_ones_the_index_counts():
    have = marked()
    for row in ("6.1", "6.2", "6.3", "6.4", "6.11"):
        assert any(n.startswith("test_connect_p1_rows.py::") for n in have[row])
    assert any(n.startswith("test_connect_p1_rows.py::") for n in have["6.18"])
    assert len([n for n in have["6.9"] if n.startswith("test_connect_p1_rows.py::")]) >= 4
