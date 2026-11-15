"""Write the two D-BIEK alias files (run from backend/: python -I ../docs/research/batches/w12/biek/make_aliases.py).

Nothing is typed by hand:
- the verdicts come from checks/alias-check1.yaml and checks/alias-check2.yaml, and must be the ones in the controller
  ruling (PLAN below); any difference stops the script;
- evidence = the BIEK line in the W12 workbook (source_url, source_quote);
- target_evidence = the target row's source_url and source_quote, from batch 3 v4 (SD-COL-*) or the same W12 workbook;
- each alias file is bound to its workbook's sha256.
Mapping (brief): check 1 same -> correct, unclear -> unclear; check 2 same -> yes, unclear -> approved left empty
(format.yaml check2_values has no `unclear`; controller ruling 2026-11-15), the verdict kept in a YAML comment.
"""

import hashlib
from pathlib import Path

import openpyxl
import yaml

HERE = Path(__file__).resolve().parent
BATCHES = HERE.parents[1]
DATE = "2026-11-15"
REF1, REF2 = "claude-w12-biek-alias-check-1", "claude-w12-biek-alias-check-2"
GOV, PVT = "biek-affiliated-government-colleges", "biek-affiliated-private-colleges"
WB = {GOV: BATCHES / "PAI-Research-W12-biek-affiliated-government-colleges.xlsx",
      PVT: BATCHES / "PAI-Research-W12-biek-affiliated-private-colleges.xlsx"}
PREFIX = {GOV: "SD-BIEK-GOV-", PVT: "SD-BIEK-PVT-"}
BATCH3 = BATCHES / "PAI-Research-Batch3-Sindh-v4.xlsx"

# (list, from key, target id, check 1 verdict, check 2 verdict): the controller ruling (brief, ledger 2026-11-15)
PLAN = {GOV: [(GOV, k, t, "same", "same") for k, t in
              [("1", "SD-COL-KQ2215"), ("3", "SD-COL-KQ2172"), ("4", "SD-COL-KQ2173"), ("5", "SD-COL-KQ2193"),
               ("8", "SD-COL-KQ2167"), ("9", "SD-COL-KQ2158"), ("11", "SD-COL-KQ2207"), ("12", "SD-COL-KQ2273"),
               ("14", "SD-COL-KQ2194"), ("15", "SD-COL-KQ2232"), ("37", "SD-COL-KQ2339")]]
        + [(GOV, "6", "SD-COL-KQ2150", "same", "unclear"), (GOV, "7", "SD-COL-KQ2163", "same", "unclear"),
           (GOV, "27", "SD-COL-KQ2236", "unclear", "unclear"), (GOV, "181", "SD-BIEK-GOV-95", "unclear", "same")],
        PVT: [(PVT, "42", "SD-BIEK-PVT-34", "same", "same"), (PVT, "50", "SD-BIEK-PVT-48", "unclear", "unclear")]}
C1 = {"same": "correct", "unclear": "unclear"}
C2 = {"same": "yes", "unclear": None}


def verdicts(path: Path) -> dict:
    """(list, from key, target id) -> verdict, for every pair the check file judged."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: dict = {}
    for v in doc.values():
        if not isinstance(v, list):
            continue
        for it in v:
            if not isinstance(it, dict) or "verdict" not in it:
                continue
            if "biek" in it and "batch" in it:
                out[(it["biek"]["list_id"], str(it["biek"]["key"]), it["batch"]["inst_id"])] = it["verdict"]
            elif "a" in it and "b" in it and it["a"]["list_id"] == it["b"]["list_id"]:
                lst = it["a"]["list_id"]
                lo, hi = sorted([str(it["a"]["key"]), str(it["b"]["key"])], key=int)
                out[(lst, hi, PREFIX[lst] + lo)] = it["verdict"]
    return out


def rows(path: Path) -> dict:
    ws = openpyxl.load_workbook(path, read_only=True)["Institutions"]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    return {r[head.index("inst_id")]: dict(zip(head, r)) for r in it if r and r[head.index("inst_id")]}


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    v1, v2 = verdicts(HERE / "checks" / "alias-check1.yaml"), verdicts(HERE / "checks" / "alias-check2.yaml")
    batch3 = rows(BATCH3)
    for lst, plan in PLAN.items():
        wb_rows = rows(WB[lst])
        sha = hashlib.sha256(WB[lst].read_bytes()).hexdigest()
        lines = [f"# Aliases for {WB[lst].name} (import --aliases; docs/research/batches/README.md, 'Alias files').",
                 "# Made by w12/biek/make_aliases.py. Verdicts: w12/biek/checks/alias-check1.yaml (check 1) and",
                 "# alias-check2.yaml (check 2, independent). Controller ruling 2026-11-15: an alias is accepted only",
                 "# where both checks say same. Every alias is required: one not accepted rejects its row, so no",
                 "# duplicate entity is loaded. Check 2 `unclear` has no value in format.yaml check2_values, so",
                 "# `approved` is left empty and the verdict is kept in a comment on that alias.",
                 f"file: {WB[lst].name}", f"sha256: {sha}", "aliases:"]
        for (l, key, to, e1, e2) in plan:
            got = (v1.get((l, key, to)), v2.get((l, key, to)))
            if got != (e1, e2):
                raise SystemExit(f"{l} {key} -> {to}: check files say {got}, the ruling says {(e1, e2)}")
            src = wb_rows[PREFIX[l] + key]
            tgt = batch3.get(to) or wb_rows.get(to)
            if tgt is None:
                raise SystemExit(f"target {to} not found")
            lines.append(f"  - from: {PREFIX[l] + key}")
            lines.append(f"    # check 1: {e1}; check 2: {e2} -> " + ("accepted" if (e1, e2) == ("same", "same")
                                                                      else "not accepted (held)"))
            lines.append(f"    to: {to}")
            lines.append(f"    evidence: {{url: {q(src['source_url'])}, quote: {q(src['source_quote'])}}}")
            lines.append(f"    target_evidence: {{url: {q(tgt['source_url'])}, quote: {q(tgt['source_quote'])}}}")
            lines.append(f"    check1: {{result: {C1[e1]}, name: \"{REF1}\", date: \"{DATE}\"}}")
            if C2[e2]:
                lines.append(f"    check2: {{approved: \"{C2[e2]}\", name: \"{REF2}\", date: \"{DATE}\"}}")
            else:
                lines.append(f"    # check 2 verdict: unclear (recorded in alias-check2.yaml); approved left empty")
                lines.append(f"    check2: {{name: \"{REF2}\", date: \"{DATE}\"}}")
            lines.append("    required: true")
        out = WB[lst].with_name(WB[lst].stem + ".aliases.yaml")
        out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out.name}: {len(plan)} aliases, bound to sha256 {sha}")


if __name__ == "__main__":
    main()
