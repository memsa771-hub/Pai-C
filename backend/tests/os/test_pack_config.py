"""Slice 6a Task 2: the pack config per route, validated at startup (spec S6a-D2, D4, D6, D12)."""

import re
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI

from app.os.documents.types import load_document_types
from app.os.eligibility.rules import profile_keys
from app.os.knowledge.profile import load_profile_dir
from app.os.packs.config import PACK_DIR, PackConfigError, check_pack_config, load_pack_configs
from app.os.playbooks import load_playbook_dir

FAKE_PACKS = Path(__file__).parent / "fixtures" / "packs"
FAKE_BOOKS = Path(__file__).parent / "playbooks"
TYPES = load_document_types()
KEYS = profile_keys(TYPES)
BOOKS = {**load_playbook_dir(), **load_playbook_dir(FAKE_BOOKS)}
PROFILES = load_profile_dir()


def book(route: str):
    return next(b for (key, _), b in BOOKS.items() if key == route)


def profile(route: str):
    return next((p for p in PROFILES.values() if p.route_key == route), None)


def check(cfg) -> None:
    check_pack_config(cfg, KEYS, set(TYPES), book(cfg.route_key), profile(cfg.route_key))


def bad(tmp_path: Path, mutate) -> Path:
    """A copy of the Germany config with one change, in its own directory."""
    raw = yaml.safe_load((PACK_DIR / "germany_master.yaml").read_text(encoding="utf-8"))
    mutate(raw)
    (tmp_path / "germany_master.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return tmp_path


def test_all_pack_configs_load():
    real, fake = load_pack_configs(), load_pack_configs(FAKE_PACKS)
    assert set(real) == {"germany_master"} and set(fake) == {"ireland_master", "pakistan_bs"}
    for cfg in [*real.values(), *fake.values()]:
        check(cfg)
    g = real["germany_master"]
    assert set(g.instructions) == {"uni_assist", "uni_assist_vpd", "direct"}
    assert {i.kind for i in g.checklist} == {"document", "statement", "manual"}
    assert any(f.source == "entered" for s in g.data_sheet for f in s.fields)
    assert g.formats.default.max_mb > 0 and g.formats.default.types == ["pdf"]


def test_unknown_profile_key_stops_startup(tmp_path):
    cfg = load_pack_configs(bad(tmp_path, lambda r: r["data_sheet"][0]["fields"][0].update(source="passport.shoe_size")))
    with pytest.raises(PackConfigError, match=r"germany_master.*passport\.shoe_size"):
        check(cfg["germany_master"])


def test_unknown_route_value_stops_startup(tmp_path):
    cfg = load_pack_configs(bad(tmp_path, lambda r: r["instructions"].update(by_pigeon=r["instructions"]["direct"])))
    with pytest.raises(PackConfigError, match="by_pigeon"):
        check(cfg["germany_master"])


def test_unknown_fact_or_citation_stops_startup(tmp_path):
    def fact(r):
        r["instructions"]["direct"][0]["source"] = "fact:shoe_size"

    def citation(r):
        r["instructions"]["direct"][0]["source"] = "citation:S999"

    def placeholder(r):
        r["instructions"]["direct"][0]["text"] = "Apply before {moon_phase}."

    for mutate, word in ((fact, "shoe_size"), (citation, "S999"), (placeholder, "moon_phase")):
        cfg = load_pack_configs(bad(tmp_path, mutate))["germany_master"]
        with pytest.raises(PackConfigError, match=word):
            check(cfg)


def test_entered_item_must_name_entered_field(tmp_path):
    def mutate(r):
        r["checklist"].append({"key": "phone", "label": "Phone", "kind": "entered", "ref": "passport_number"})

    cfg = load_pack_configs(bad(tmp_path, mutate))["germany_master"]
    with pytest.raises(PackConfigError, match="passport_number"):
        check(cfg)


def test_unknown_document_type_or_format_stops_startup(tmp_path):
    for mutate, word in ((lambda r: r["checklist"][0].update(ref="library_card"), "library_card"),
                         (lambda r: r["checklist"][0].update(format="hologram"), "hologram")):
        cfg = load_pack_configs(bad(tmp_path, mutate))["germany_master"]
        with pytest.raises(PackConfigError, match=word):
            check(cfg)


def test_mount_validates_pack_configs(tmp_path):
    from app.os.api.mount import mount_os

    pack_dir = bad(tmp_path, lambda r: r["data_sheet"][0]["fields"][0].update(source="passport.shoe_size"))
    env = {"OS_DATABASE_URL": "postgresql://unused/x", "OS_ENABLED": "true"}
    with pytest.raises(PackConfigError, match="shoe_size"):
        mount_os(FastAPI(), env=env, pack_dir=pack_dir)
    assert mount_os(FastAPI(), env=env) is True  # the real configs are valid


def test_no_country_terms_in_packs_python():
    """Invariant 12: no country, portal or currency name in the packs code."""
    words = re.compile(r"germany|german|deutsch|ireland|pakistan|uni-?assist|\beur\b|euro|\bpkr\b|daad|\bhec\b",
                       re.IGNORECASE)
    hits = [f"{p.name}:{n}" for p in Path(PACK_DIR).glob("*.py")
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if words.search(line)]
    assert hits == []
