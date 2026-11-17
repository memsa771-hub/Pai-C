"""Write the D-PMDC alias file (run from backend/: python -I ../docs/research/batches/w12/pmdc/make_aliases.py).

Nothing is typed by hand:
- the verdicts come from checks/alias-check1.yaml (ref claude-w12-pmdc-alias-check-1) and checks/alias-check2.yaml
  (ref claude-w12-pmdc-alias-check-2, independent). They must be the ones in the controller ruling (ACCEPTED, HELD
  below); any difference stops the script;
- evidence = the PMDC line: the list url and the row's source_quote in the W12 workbook. For a line the workbook holds
  (name_disagrees), the quote is the `quote` cell of the two extractions, which must be equal;
- target_evidence = the target row's source_url and source_quote in the batch 1-5 v4 file it lives in (one file only);
- the file is bound to the workbook's sha256.
Ruling (brief, 2026-11-15): accepted only where both checks say `same` for the same target (74 pairs). Held: keys 18,
56, 104, 141, 145, 163, 164, 166, with the target check 1 names (alias_target) or, where it names none, check 1's first
listed candidate. Mapping: check 1 same -> correct, unclear -> unclear; check 2 same -> yes, unclear -> `approved` left
empty (format.yaml check2_values has no `unclear`), the verdict kept in a YAML comment. Every alias is required.
"""

import csv
import hashlib
from pathlib import Path

import openpyxl
import yaml

HERE = Path(__file__).resolve().parent
BATCHES = HERE.parents[1]
LISTS = BATCHES.parent / "lists" / "national.yaml"
DATE = "2026-11-15"
REF1, REF2 = "claude-w12-pmdc-alias-check-1", "claude-w12-pmdc-alias-check-2"
LIST_ID = "pmdc-colleges-with-hospitals"
PREFIX = "PK-PMDC-"
WB = BATCHES / "PAI-Research-W12-pmdc-colleges-with-hospitals.xlsx"
CSV = "pmdc-colleges-with-hospitals.csv"
V4 = sorted(BATCHES.glob("PAI-Research-Batch[1-5]-*-v4.xlsx"))
N_ACCEPTED = 74
HELD = (18, 56, 104, 141, 145, 163, 164, 166)
C1 = {"same": "correct", "unclear": "unclear"}
C2 = {"same": "yes", "unclear": None}


def rows(path: Path) -> dict:
    ws = openpyxl.load_workbook(path, read_only=True)["Institutions"]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    i = head.index("inst_id")
    return {r[i]: dict(zip(head, r)) for r in it if r and r[i]}


def q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def main() -> None:
    c1 = yaml.safe_load((HERE / "checks" / "alias-check1.yaml").read_text(encoding="utf-8"))
    c2 = yaml.safe_load((HERE / "checks" / "alias-check2.yaml").read_text(encoding="utf-8"))
    if c1["check"]["ref"] != REF1 or c2["check"]["ref"] != REF2 or str(c1["check"]["date"]) != DATE \
            or str(c2["check"]["date"]) != DATE:
        raise SystemExit(f"check refs/dates are not {REF1}, {REF2}, {DATE}")
    l1 = {int(x["key"]): x for x in c1["lines"]}
    l2 = {int(x["key"]): x for x in c2["lines"]}
    # pairs both checks judge same, for the same target
    same1 = {k: x["alias_target"] for k, x in l1.items() if x.get("alias_target")
             and any(c["inst_id"] == x["alias_target"] and c["verdict"] == "same" for c in x["candidates"])}
    same2 = {k: x["target"] for k, x in l2.items() if x.get("verdict") == "same" and x.get("target")
             and any(p["inst_id"] == x["target"] and p["verdict"] == "same" for p in x["pairs"])}
    accepted = {k: t for k, t in same1.items() if same2.get(k) == t}
    if len(accepted) != N_ACCEPTED or set(same2) - set(accepted):
        raise SystemExit(f"both-same pairs: {len(accepted)} (ruling {N_ACCEPTED}); check 2 only: "
                         f"{sorted(set(same2) - set(accepted))}")
    if set(accepted) & set(HELD):
        raise SystemExit(f"a held key is accepted: {sorted(set(accepted) & set(HELD))}")
    unsettled = sorted(set(same1) - set(accepted)
                       | {k for k, x in l1.items() if any(c["verdict"] == "unclear" for c in x["candidates"])}
                       | {k for k, x in l2.items() if x.get("verdict") == "unclear"})
    if unsettled != sorted(HELD):
        raise SystemExit(f"lines not settled by both checks: {unsettled}; the ruling holds {sorted(HELD)}")

    plan = []  # (key, target, check 1 verdict, check 2 verdict, comment)
    for k in sorted([*accepted, *HELD]):
        x1, x2 = l1[k], l2[k]
        if k in accepted:
            plan.append((k, accepted[k], "same", "same", None))
            continue
        if x1.get("alias_target"):
            to, why = x1["alias_target"], "check 1 names this alias_target"
        else:
            to = x1["candidates"][0]["inst_id"]
            why = ("check 1 names no alias_target; its only candidate" if len(x1["candidates"]) == 1 else
                   f"check 1 names no single target; its first listed candidate (of "
                   f"{', '.join(c['inst_id'] for c in x1['candidates'])})")
        v1 = next(c["verdict"] for c in x1["candidates"] if c["inst_id"] == to)
        v2 = next((p["verdict"] for p in x2["pairs"] if p["inst_id"] == to), None)
        if (v1, v2) not in (("same", "unclear"), ("unclear", "unclear")):
            raise SystemExit(f"held {k} -> {to}: check 1 {v1}, check 2 {v2}")
        plan.append((k, to, v1, v2, why))

    lst = next(x for x in yaml.safe_load(LISTS.read_text(encoding="utf-8"))["lists"] if x["id"] == LIST_ID)
    wb_rows = rows(WB)
    ext = {x: {r["key"]: r for r in csv.DictReader((HERE / x / CSV).open(encoding="utf-8", newline=""))}
           for x in ("E1", "E2")}
    v4 = {f.name: rows(f) for f in V4}
    sha = hashlib.sha256(WB.read_bytes()).hexdigest()
    lines = [f"# Aliases for {WB.name} (import --aliases; docs/research/batches/README.md, 'Alias files').",
             "# Made by w12/pmdc/make_aliases.py. Verdicts: w12/pmdc/checks/alias-check1.yaml (check 1) and",
             "# alias-check2.yaml (check 2, independent). Controller ruling 2026-11-15: an alias is accepted only where",
             "# both checks say same (74). Held (not accepted): 18, 56, 104, 141, 145, 163, 164, 166. Every alias is",
             "# required: one not accepted rejects its row, so no duplicate entity is loaded. Check 2 `unclear` has no",
             "# value in format.yaml check2_values, so `approved` is left empty and the verdict is kept in a comment.",
             f"file: {WB.name}", f"sha256: {sha}", "aliases:"]
    on_held_rows = []
    for k, to, e1, e2, why in plan:
        fid = PREFIX + str(k)
        src = wb_rows.get(fid)
        if src is not None:
            url, quote = src["source_url"], src["source_quote"]
        else:  # the workbook holds this line (the extractions disagree on the name); their quotes must agree
            a, b = ext["E1"][str(k)]["quote"], ext["E2"][str(k)]["quote"]
            if a != b:
                raise SystemExit(f"{fid}: held row and the two quotes differ")
            url, quote = lst["url"], a
            on_held_rows.append(k)
        found = [(n, r[to]) for n, r in v4.items() if to in r]
        if len(found) != 1:
            raise SystemExit(f"target {to}: in {len(found)} batch v4 files")
        tname, tgt = found[0]
        status = "accepted" if (e1, e2) == ("same", "same") else "not accepted (held)"
        lines.append(f"  - from: {fid}")
        lines.append(f"    # check 1: {e1}; check 2: {e2} -> {status}; target in {tname}")
        if why:
            lines.append(f"    # target: {why}")
        if src is None:
            lines.append("    # this line is held in the workbook (name_disagrees); quote = the quote cell of E1 and E2")
        lines.append(f"    to: {to}")
        lines.append(f"    evidence: {{url: {q(url)}, quote: {q(quote)}}}")
        lines.append(f"    target_evidence: {{url: {q(tgt['source_url'])}, quote: {q(tgt['source_quote'])}}}")
        lines.append(f"    check1: {{result: {C1[e1]}, name: \"{REF1}\", date: \"{DATE}\"}}")
        if C2[e2]:
            lines.append(f"    check2: {{approved: \"{C2[e2]}\", name: \"{REF2}\", date: \"{DATE}\"}}")
        else:
            lines.append("    # check 2 verdict: unclear (recorded in alias-check2.yaml); approved left empty")
            lines.append(f"    check2: {{name: \"{REF2}\", date: \"{DATE}\"}}")
        lines.append("    required: true")
    out = WB.with_name(WB.stem + ".aliases.yaml")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {out.name}: {len(plan)} aliases ({len(accepted)} accepted, {len(HELD)} held), bound to sha256 {sha}")
    print(f"accepted aliases whose line the workbook holds: {on_held_rows}")


if __name__ == "__main__":
    main()
