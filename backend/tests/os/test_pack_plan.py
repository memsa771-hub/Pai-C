"""Slice 6a Task 4: the `required_documents` research field and the `review_pack` plan task (spec S6a-D2, D8, D11)."""

from pathlib import Path
from types import SimpleNamespace

from app.os.knowledge.profile import load_profile_dir
from app.os.packs.config import load_pack_configs
from app.os.playbooks import load_playbook_dir
from tests.os.quality.scoring import score

FAKE_BOOKS = Path(__file__).parent / "playbooks"
BOOKS = {key: b for (key, _), b in {**load_playbook_dir(), **load_playbook_dir(FAKE_BOOKS)}.items()}
# per route: the task review_pack follows, and the tasks that must follow review_pack
ORDER = {
    "germany_master": ("application_documents", {"uni_assist_apply", "direct_apply"}),
    "ireland_master": (None, {"apply"}),
    "pakistan_bs": (None, {"merit_list"}),
}


def task(book, key):
    return next((t for t in book.tasks if t.template_key == key), None)


def test_review_pack_in_each_route():
    for route, (after, before) in ORDER.items():
        book = BOOKS[route]
        t = task(book, "review_pack")
        assert t is not None, route
        assert (t.task_type, t.kind, t.inbox_kind, t.fan_out) == ("student.approve", "student", "approve", "programme")
        assert [d.key for d in t.depends_on] == ([after] if after else [])
        for key in before:
            assert "review_pack" in {d.key for d in task(book, key).depends_on}, (route, key)


def test_required_documents_field_in_profile():
    profile = next(p for p in load_profile_dir().values() if p.route_key == "germany_master")
    f = next(f for f in profile.fields if f.name == "required_documents")
    assert f.type == "name_set"
    checklist = {i.key for i in load_pack_configs()["germany_master"].checklist}
    assert set(f.values) - {"other"} <= checklist  # every researched item is one the pack knows


def test_review_pack_cites_required_documents():
    assert task(BOOKS["germany_master"], "review_pack").citation_from_fact == "required_documents"


def test_application_fee_constant_cited():
    c = BOOKS["germany_master"].constants["uni_assist_fee_eur"]
    assert isinstance(c.value, int) and c.citations


def test_spike1_scorer_skips_required_documents():
    """The Spike 1 answer key has no required_documents: researching it must not change the score."""
    key = {"p1": {"key_status": "confirmed", "facts": {}}}
    verdicts = {"p1": {"required_documents": SimpleNamespace(status="confirmed", value=["passport"], reasons=[],
                                                              url="u", quote="q")}}
    assert score(key, verdicts, ["required_documents"]).scored == 0
