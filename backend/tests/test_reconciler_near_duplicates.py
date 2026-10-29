# -*- coding: utf-8 -*-
"""Audit #6: near-identical entries of one type are one entry, shown as one line."""

from sqlalchemy import select

from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler, _policy
from app.memory.vault_view import VaultView
from app.models import VaultItem
from scripts.counselor_eval_support import StudentSession


def _run(db, ws, key, value, quote="q", **evidence):
    candidate = MemoryCandidateService(db).propose(
        ws, "vault_item", key=key, proposed_value=value, confidence=0.9, source_type="conversation",
        evidence={"quote": quote, **evidence})
    return MemoryReconciler(db).reconcile(candidate)


def _active(db, ws, item_type):
    return db.scalars(select(VaultItem).where(VaultItem.workspace_id == ws, VaultItem.item_type == item_type,
                                              VaultItem.status == "active")).all()


def test_6_threshold_lives_in_data():
    assert _policy()["near_duplicate"]["min_jaccard"] == 0.8
    assert _policy()["near_duplicate"]["fields"]["strength"] == "text"


def test_6_near_duplicate_strengths_merge_into_the_earliest():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        first = _run(db, ws, "strength", {"text": "Good at maths"}, inferred=True)
        for text in ("good at math", "Good at maths.", "GOOD AT MATHS"):
            again = _run(db, ws, "strength", {"text": text}, quote=text)
            assert again.accepted
        other = _run(db, ws, "strength", {"text": "Explains physics to friends"})
        db.commit()
        rows = _active(db, ws, "strength")
        assert len(rows) == 2 and other.result_id in {r.id for r in rows}
        [maths] = [r for r in rows if r.id != other.result_id]
        assert maths.value == {"text": "Good at maths"}  # the earliest wording
        assert maths.level == "stated"  # raised: the student said it after PAI guessed it
        assert maths.id == first.result_id
        assert len(maths.evidence["corroborations"]) == 3
        view = VaultView(db).build(ws)
        lines = [e["display"] for card in view["story"] if card["type"] == "strength" for e in card["entries"]]
        assert sorted(lines) == ["Explains physics to friends", "Good at maths"]


def test_6_a_different_option_status_still_updates_the_entry():
    with StudentSession() as student, student.factory() as db:
        ws = student.workspace_id
        _run(db, ws, "option", {"text": "Medicine", "status": "considering"})
        _run(db, ws, "option", {"text": "medicine", "status": "ruled_out"})
        db.commit()
        [row] = _active(db, ws, "option")
        assert row.value == {"text": "Medicine", "status": "ruled_out"}
