"""Write the D-FDE alias file (WITHDRAWN by the controller ruling 2026-11-15: not committed, not imported; see README) (run from backend/: python -I ../docs/research/batches/w12/fde/make_aliases.py).

Nothing is typed by hand:
- the verdicts come from checks/alias-check1.yaml (ref claude-w12-fde-alias-check-1) and checks/alias-check2.yaml
  (ref claude-w12-fde-alias-check-2, independent). Every pair either file judges `same` is collected; the script stops
  unless both files give exactly the pairs in PLAN (the controller ruling) and nothing else;
- evidence = the FDE line in the W12 workbook (its source_url, the list url, and its source_quote);
- target_evidence = the target row's source_url and source_quote, from batch 4 v4;
- the alias file is bound to the workbook's sha256.
Mapping: check 1 same -> `correct`; check 2 same -> `yes`. Every alias is required and dated 2026-11-15.
"""

import hashlib
from pathlib import Path

import openpyxl
import yaml

HERE = Path(__file__).resolve().parent
BATCHES = HERE.parents[1]
DATE = "2026-11-15"
REF1, REF2 = "claude-w12-fde-alias-check-1", "claude-w12-fde-alias-check-2"
WB = BATCHES / "PAI-Research-W12-fde-hssc-participating-colleges.xlsx"
PREFIX = "IC-FDECOL-"
BATCH4 = BATCHES / "PAI-Research-Batch4-KP-Bal-ICT-AJK-GB-v4.xlsx"

# (from key, target id): the controller ruling (brief; ledger 2026-11-15, D-FDE alias checks 1 and 2)
PLAN = [("78", "IC-COL-001")]


def same_pairs(path: Path, ref: str) -> set:
    """Every (FDE key, target id) the check file judges `same`, from any list of judged items in it."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    got = doc.get("check") or doc.get("ref")
    if got != ref:
        raise SystemExit(f"{path.name}: ref is {got!r}, expected {ref!r}")
    out: set = set()
    judged = 0
    for v in doc.values():
        if not isinstance(v, list):
            continue
        for it in v:
            if not isinstance(it, dict) or "verdict" not in it or "fde_key" not in it:
                continue
            judged += 1
            if it["verdict"] == "same":
                ids = it["inst_id"] if isinstance(it["inst_id"], list) else [it["inst_id"]]
                for t in ids:
                    out.add((str(it["fde_key"]), str(t)))
    if not judged:
        raise SystemExit(f"{path.name}: no judged items found")
    return out


def rows(path: Path) -> dict:
    ws = openpyxl.load_workbook(path, read_only=True)["Institutions"]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    return {r[head.index("inst_id")]: dict(zip(head, r)) for r in it if r and r[head.index("inst_id")]}


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    s1 = same_pairs(HERE / "checks" / "alias-check1.yaml", REF1)
    s2 = same_pairs(HERE / "checks" / "alias-check2.yaml", REF2)
    if s1 != set(PLAN) or s2 != set(PLAN):
        raise SystemExit(f"check 1 same: {sorted(s1)}; check 2 same: {sorted(s2)}; the ruling says {PLAN}")
    wb_rows, batch4 = rows(WB), rows(BATCH4)
    sha = hashlib.sha256(WB.read_bytes()).hexdigest()
    lines = [f"# Aliases for {WB.name} (import --aliases; docs/research/batches/README.md, 'Alias files').",
             "# Made by w12/fde/make_aliases.py. Verdicts: w12/fde/checks/alias-check1.yaml (check 1) and",
             "# alias-check2.yaml (check 2, independent). Controller ruling 2026-11-15: an alias is accepted only",
             "# where both checks say same. The alias is required, so its row never loads a duplicate entity.",
             f"file: {WB.name}", f"sha256: {sha}", "aliases:"]
    for key, to in PLAN:
        src = wb_rows[PREFIX + key]
        tgt = batch4.get(to)
        if tgt is None:
            raise SystemExit(f"target {to} not found in {BATCH4.name}")
        lines.append(f"  - from: {PREFIX + key}")
        lines.append("    # check 1: same; check 2: same -> accepted")
        lines.append(f"    to: {to}")
        lines.append(f"    evidence: {{url: {q(src['source_url'])}, quote: {q(src['source_quote'])}}}")
        lines.append(f"    target_evidence: {{url: {q(tgt['source_url'])}, quote: {q(tgt['source_quote'])}}}")
        lines.append(f"    check1: {{result: correct, name: \"{REF1}\", date: \"{DATE}\"}}")
        lines.append(f"    check2: {{approved: \"yes\", name: \"{REF2}\", date: \"{DATE}\"}}")
        lines.append("    required: true")
    out = WB.with_name(WB.stem + ".aliases.yaml")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name}: {len(PLAN)} alias(es), bound to sha256 {sha}")


if __name__ == "__main__":
    main()
