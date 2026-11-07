"""P2-T6: ONE read-only dry run of the real v4 batch files, to prove the mapping on the real layouts (owner message
2026-11-07). It reads the workbooks and the official-list files from the research checkout and touches no database.
Skipped when the checkout is absent. It asserts the accounting and the layout detection, not the research data."""

from pathlib import Path

import pytest
import yaml

from app.os.knowledge.sheets.importer import plan_file
from app.os.knowledge.sheets.plan import PlanContext, norm_url, summarise
from app.os.registry.lists import parse_official_lists

DATA = Path("/home/user/Pai-C-data/docs/research")
pytestmark = [pytest.mark.req("R-67"), pytest.mark.skipif(not (DATA / "batches").is_dir(),
                                                           reason="research checkout not present")]
ROWS = {  # source rows per sheet in each v4 file (Institutions, Programmes incl. placeholders, Facts)
    "PAI-Research-Batch1-National-v4.xlsx": (354, 1, 65, "programmes_batch1"),
    "PAI-Research-Batch2-Punjab-v4.xlsx": (79, 96, 79, "programmes_seats_closing"),
    "PAI-Research-Batch3-Sindh-v4.xlsx": (72, 146, 46, "programmes_cut_off"),
    "PAI-Research-Batch4-KP-Bal-ICT-AJK-GB-v4.xlsx": (46, 41, 86, None),
    "PAI-Research-Batch5-Universities-BS-v4.xlsx": (19, 13, 60, "programmes_merit_formula"),
}


def list_urls() -> dict[str, str]:
    out = {}
    for f in sorted((DATA / "lists").glob("*.yaml")):
        for e in parse_official_lists(yaml.safe_load(f.read_text(encoding="utf-8")), country="PK"):
            out[norm_url(e.source_url)] = e.entity_id
    return out


def test_the_five_v4_files_map_and_every_row_is_accounted_for():
    ctx = lambda: PlanContext(country="PK", list_urls=list_urls())  # noqa: E731
    verified = 0
    for name, (n_inst, n_prog, n_fact, layout) in ROWS.items():
        batch, results = plan_file(DATA / "batches" / name, ctx())
        assert batch.layouts.get("Programmes") == layout, name
        assert len(batch.sheets["Institutions"]) == n_inst and len(batch.sheets["Facts"]) == n_fact, name
        counts = summarise(results)
        for sheet, rows in (("Institutions", n_inst), ("Facts", n_fact)):
            assert sum(counts[sheet][b] for b in ("accepted", "unconfirmed", "queued", "rejected", "skipped")) == rows
        assert all(r.reason for r in results), "every row has a reason"
        verified += sum(c.get("verified", 0) for c in counts.values())
        # the owner-accepted checks are recognised on every row that has them
        assert not any("not a check the owner accepted" in r.detail for r in results), name
    assert verified > 400
