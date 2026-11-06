"""P1-T9 Task 1: a playbook version declares its plan pages and the dates its sources were checked, in a sidecar
file next to it (R-51, R-52, R-54). Fictional data: the shipped Germany playbook and the fake routes."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.os.playbooks import PAGE_KEYS, PLAYBOOK_DIR, Page, PlaybookError, SourceCheck, load_playbook_dir
from app.os.playbooks.models import Playbook

FAKE = Path(__file__).parent / "playbooks"
SHIPPED = load_playbook_dir(PLAYBOOK_DIR)
FAKES = load_playbook_dir(FAKE)
GERMANY = SHIPPED[("germany_master", 1)]

# Today's menu and headings (frontend os-nav-group.tsx OS_PAGES, en-US nav labels, and the page headings).
TODAY = [("start", "Start", "Start your plan"), ("inbox", "Inbox", "Your next steps"),
         ("documents", "Documents", "Your documents"), ("programmes", "Programmes", "Your programmes"),
         ("statements", "Statements", "Your statement and CV"), ("pack", "Pack", "Your application packs"),
         ("visa", "Visa", "Your visa file")]


def book(**over) -> dict:
    """A small playbook as data; `over` replaces top-level fields."""
    data = {"key": "x", "version": 1, "route": {"origin": "AA", "destination": "BB", "level": "master"},
            "default_timezone": "UTC",
            "tasks": [{"template_key": "t", "task_type": "work.t", "title": "T", "kind": "work"}]}
    return {**data, **over}


@pytest.mark.req("R-51")
def test_every_playbook_declares_its_pages():
    books = {**SHIPPED, **FAKES}
    assert len(books) == 4
    for ident, b in books.items():
        assert b.pages is not None, ident


@pytest.mark.req("R-52")
def test_germany_pages_are_todays_menu():
    assert tuple(p.key for p in GERMANY.pages) == PAGE_KEYS
    assert [(p.key, p.label, p.title) for p in GERMANY.pages] == TODAY
    nouns = {p.key: p.noun for p in GERMANY.pages if p.noun}
    assert nouns == {"pack": "pack", "visa": "visa file"}


def test_fake_routes_declare_only_what_they_have():
    keys = {k: [p.key for p in b.pages] for (k, _), b in FAKES.items()}
    assert keys == {"ireland_master": ["inbox", "documents", "programmes"],
                    "pakistan_bs": ["inbox", "documents", "programmes"],
                    "pakistan_inter": ["inbox", "documents"]}
    for b in FAKES.values():
        for p in b.pages:
            assert not {"visa", "abroad"} & set((p.label + " " + p.title).lower().split())


def test_visa_page_needs_a_route_that_leaves_the_country():
    page = {"key": "visa", "label": "Visa", "title": "Your visa file"}
    with pytest.raises(ValidationError, match="visa"):
        Playbook.model_validate(book(route={"origin": "AA", "destination": "AA", "level": "master"}, pages=[page]))
    assert Playbook.model_validate(book(pages=[page])).pages[0].key == "visa"


def test_unknown_or_duplicate_page_key_is_refused():
    ok = {"key": "inbox", "label": "Inbox", "title": "Your next steps"}
    with pytest.raises(ValidationError):
        Playbook.model_validate(book(pages=[{**ok, "key": "elsewhere"}]))
    with pytest.raises(ValidationError, match="duplicate"):
        Playbook.model_validate(book(pages=[ok, ok]))
    with pytest.raises(ValidationError):
        Page.model_validate({**ok, "extra": 1})


def test_noun_only_on_pack_and_visa():
    ok = {"key": "inbox", "label": "Inbox", "title": "Your next steps"}
    with pytest.raises(ValidationError, match="noun"):
        Playbook.model_validate(book(pages=[{**ok, "noun": "pile"}]))
    assert Playbook.model_validate(book(pages=[{**ok, "key": "pack", "noun": "pile"}])).pages[0].noun == "pile"


@pytest.mark.req("R-54")
def test_germany_sources_dated_from_the_walkthrough():
    """spike5-germany-playbook.md section 5: 'Checked 2026-10-17' for S1..S18."""
    assert set(GERMANY.sources) == {f"S{n}" for n in range(1, 19)}
    assert all(s.checked == date(2026, 10, 17) for s in GERMANY.sources.values())
    # spike5 section 6: the reviewer did not tick S8, S13, S14, S17 and S18; they are not shown as confirmed.
    assert {k for k, s in GERMANY.sources.items() if not s.confirmed} == {"S8", "S13", "S14", "S17", "S18"}
    cited = {c.source for t in GERMANY.tasks for c in t.citations} | \
            {c.source for k in GERMANY.constants.values() for c in k.citations}
    assert cited and cited <= set(GERMANY.sources)


@pytest.mark.req("R-54")
def test_undated_source_is_refused_when_sources_are_declared():
    cite = {"source": "S9", "url": "https://example.test/x"}
    tasks = [{"template_key": "t", "task_type": "work.t", "title": "T", "kind": "work", "citations": [cite]}]
    with pytest.raises(ValidationError, match="S9"):
        Playbook.model_validate(book(tasks=tasks, sources={"S1": {"checked": "2026-10-17"}}))
    with pytest.raises(ValidationError):
        SourceCheck.model_validate({})
    # no sources declared: nothing to check (the fake routes cite nothing)
    assert Playbook.model_validate(book(tasks=tasks)).sources == {}


def test_sidecar_is_joined_by_key_and_version(tmp_path):
    src = yaml.safe_dump(book())
    (tmp_path / "x.v1.yaml").write_text(src)
    (tmp_path / "x.v2.yaml").write_text(src.replace("version: 1", "version: 2"))
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "x.v1.yaml").write_text(yaml.safe_dump(
        {"pages": [{"key": "inbox", "label": "Inbox", "title": "Your next steps"}]}))
    books = load_playbook_dir(tmp_path)
    assert [p.key for p in books[("x", 1)].pages] == ["inbox"]
    assert books[("x", 2)].pages is None  # no sidecar, no pages


def test_sidecar_may_hold_only_pages_and_sources(tmp_path):
    (tmp_path / "x.v1.yaml").write_text(yaml.safe_dump(book()))
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "x.v1.yaml").write_text(yaml.safe_dump({"tasks": []}))
    with pytest.raises(PlaybookError, match="x.v1.yaml"):
        load_playbook_dir(tmp_path)


def test_sidecar_without_a_playbook_is_refused(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "ghost.v1.yaml").write_text(yaml.safe_dump({"pages": []}))
    with pytest.raises(PlaybookError, match="ghost"):
        load_playbook_dir(tmp_path)


def test_playbook_files_are_untouched():
    """Invariant 10: a running plan pins its playbook version, so the display data lives beside the file."""
    for path in [*PLAYBOOK_DIR.glob("*.yaml"), *FAKE.glob("*.yaml")]:
        text = path.read_text(encoding="utf-8")
        assert "\npages:" not in text and "\nsources:" not in text, path.name
