import copy
from pathlib import Path

import pytest
import yaml

from app.os.playbooks import PlaybookError, load_playbook, load_playbook_dir, select_playbook

FAKE_DIR = Path(__file__).parent / "playbooks"
IE = FAKE_DIR / "ireland_master.v1.yaml"


def _write(tmp_path: Path, data: dict, name: str = "pb.v1.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def _ie() -> dict:
    return yaml.safe_load(IE.read_text())


def test_fake_playbooks_load():
    books = load_playbook_dir(FAKE_DIR)
    assert set(books) == {("ireland_master", 1), ("pakistan_bs", 1)}
    assert books[("ireland_master", 1)].tasks[0].fan_out == "programme"


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d["tasks"][1]["depends_on"].append({"key": "nope"}), "unknown dependency 'nope'"),
    (lambda d: d["tasks"][0].pop("inbox_kind"), "student task needs inbox_kind"),
    (lambda d: d["tasks"].append(copy.deepcopy(d["tasks"][0])), "duplicate template_key"),
    (lambda d: d.update(default_timezone="Mars/Base"), "unknown timezone"),
    (lambda d: d["tasks"][0].update(lead_time={"constant": "missing"}), "unknown constant 'missing'"),
    (lambda d: d.update(require_citations=True), "needs a citation"),
    (lambda d: d["tasks"][0].update(surprise=1), "Extra inputs"),
])
def test_invalid_playbook_rejected(tmp_path, mutate, msg):
    data = _ie()
    mutate(data)
    with pytest.raises(PlaybookError, match=msg):
        load_playbook(_write(tmp_path, data))


def test_citation_from_fact_satisfies_requirement(tmp_path):
    data = _ie()
    data["require_citations"] = True
    for t in data["tasks"]:  # one task cited from a fact, the others directly
        if t["template_key"] == "apply":
            t["citation_from_fact"] = "deadline_close"
        else:
            t["citations"] = [{"source": "S1", "url": "https://example.org/visa"}]
    assert load_playbook(_write(tmp_path, data)).require_citations


def test_select_playbook_highest_version(tmp_path):
    v1 = _ie()
    v2 = _ie()
    v2["version"] = 2
    _write(tmp_path, v1, "a.v1.yaml")
    _write(tmp_path, v2, "a.v2.yaml")
    books = load_playbook_dir(tmp_path)
    assert select_playbook(books, "PK", "IE", "master").version == 2
    with pytest.raises(PlaybookError, match="no playbook for PK->DE master"):
        select_playbook(books, "PK", "DE", "master")


def test_broken_yaml_names_file(tmp_path):
    p = tmp_path / "bad.v1.yaml"
    p.write_text("key: [unclosed")
    with pytest.raises(PlaybookError, match="bad.v1.yaml"):
        load_playbook(p)
