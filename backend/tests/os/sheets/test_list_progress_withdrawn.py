"""P2-T27 (FU-1): the progress of an official list does not count a row that an import undo withdrew (status `closed`
plus the `withdrawn_by_import` marker, the test `kept_lists` uses). A row closed or merged for any other reason still
counts, as before: whether it should is the owner's question (W10). P2 spec §4.1, gate 6; master R-35a, R-60, R-68.
Fictional data only."""

from dataclasses import replace

import pytest

from app.os.knowledge.sheets.undo import undo_import
from app.os.registry.store import WITHDRAWN

from .helpers import inst
from .test_alias_membership import alias_import, line
from .test_list_union import BETA_URL, A, B, E, do_import, loaded, two_lists

pytestmark = [pytest.mark.req("R-35"), pytest.mark.req("R-60"), pytest.mark.req("R-68")]
E2 = "inst:t-inst-002"


def progress(s) -> dict[str, int]:
    """Both readers, which must agree."""
    many = loaded(s)
    assert many == {k: s.list_progress(k).loaded for k in many}
    return many


def test_import_then_undo_gives_loaded_back_its_earlier_value(engine, clean, tmp_path):
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    assert progress(s) == {A: 1, B: 0}
    res = do_import(engine, tmp_path, [inst(2), inst(3, source_url=BETA_URL)], "b.xlsx")
    assert progress(s) == {A: 2, B: 1}
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E2).status == "closed" and WITHDRAWN in s.get(E2).attrs  # closed, kept (R-60), with its lists
    assert s.get(E2).list_ids == (A,)
    assert progress(s) == {A: 1, B: 0}


def test_a_re_import_after_undo_counts_once(engine, clean, tmp_path):
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1), inst(2)], "a.xlsx")
    undo_import(engine, "pai", first.import_id, actor="admin")
    assert progress(s) == {A: 0, B: 0}
    do_import(engine, tmp_path, [inst(1)], "b.xlsx")  # inst 2 stays withdrawn
    assert s.get(E).status == "active" and s.get(E2).status == "closed"
    assert progress(s) == {A: 1, B: 0}


def test_a_row_a_reviewer_made_active_again_counts(engine, clean, tmp_path):
    # regression pin: passes on the base too. It keeps the test at "closed plus the marker", not the marker alone.
    s = two_lists(engine)
    first = do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    undo_import(engine, "pai", first.import_id, actor="admin")
    s.record(replace(s.get(E), status="active"), cause="review")  # attrs copied: the marker is still there
    assert WITHDRAWN in s.get(E).attrs
    assert progress(s) == {A: 1, B: 0}


def test_an_undone_alias_membership_does_not_count(engine, clean, tmp_path):
    s = two_lists(engine)
    # the target and the alias list line in one file: the undo withdraws the target, which keeps both lists
    res, _ = alias_import(engine, tmp_path, [line(), inst(1)])
    assert s.get(E).list_ids == (A, B) and progress(s) == {A: 1, B: 1}
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E).status == "closed" and s.get(E).list_ids == (A, B)
    assert progress(s) == {A: 0, B: 0}


def test_an_undone_alias_membership_on_a_target_loaded_before_does_not_count(engine, clean, tmp_path):
    # regression pin: passes on the base too. The undo gives the target its list_ids back from the `add_lists`
    # revision's `before`, so the list falls without the T27 change.
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1)], "a.xlsx")
    res, _ = alias_import(engine, tmp_path, [line()])
    assert progress(s) == {A: 1, B: 1}
    undo_import(engine, "pai", res.import_id, actor="admin")
    assert s.get(E).status == "active" and s.get(E).list_ids == (A,)
    assert progress(s) == {A: 1, B: 0}


@pytest.mark.parametrize("status", ["closed", "merged"])
def test_a_row_closed_or_merged_for_another_reason_still_counts(engine, clean, tmp_path, status):
    # regression pin: passes on the base too. Today's behaviour, kept until the owner decides (W10).
    s = two_lists(engine)
    do_import(engine, tmp_path, [inst(1), inst(2)], "a.xlsx")
    successor = E2 if status == "merged" else None
    s.record(replace(s.get(E), status=status, successor_id=successor), cause="review")
    assert WITHDRAWN not in s.get(E).attrs
    assert progress(s) == {A: 2, B: 0}
