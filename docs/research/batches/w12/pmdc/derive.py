"""Controller derivation (W12 D-PMDC, 2026-11-15; v2 FU-15 the same day; for the owner to confirm). Run from this folder
or anywhere:
    python -I derive.py <this folder>
For BOTH extractions alike, from source-extractions/E1 and E2 (the agents' CSVs, unchanged), it writes E1/ and E2/ with
the columns key, name, quote, type, region, page, doc_sha256. Only two columns are added; nothing else is changed:
- type = section-types.yaml[section] (ruling 1). An unknown section stops the script.
- region, in this order:
  1. region-words.yaml[word] for the province/territory word printed in the row's address (ruling 2). The address is the
     extraction's own `address` cell; where an extraction left it empty (its whole cell is in `name`), the `name` cell is
     scanned instead. The bold remark "(Letter sent to M/o NHSR&C, Islamabad ...)" is in neither cell (both extractions
     keep it in `quote` only), so it never gives a region; a word inside the college name before the address (168
     "Sindh Medical College", 187 "Sindh Institute ...") is not used. Two different words in one row stop the script.
  2. else, for a row both FU-15 district checks judged (checks/district-check1.yaml and district-check2.yaml: the 88
     rows the D-PMDC dry run rejected missing_region, i.e. no province word and no alias), the region of the PBS 2023
     district or division named by the last comma part of the same text, under the rule in district-regions.yaml
     (exact, or space-free when exactly one name has that form; a name in two regions never matches).
  3. else empty. An alias row keeps an empty region and inherits its target's region (T28 rule 4).
  No region from any other city.
The script stops unless: district-regions.yaml `units` equals both checks' tables; both checks judged the same rows,
with the same address as each extraction's text; and step 2 gives, in E1 and in E2, exactly both checks' per-row result
(matched or not, the unit name and the region).
key, name, quote, page and doc_sha256 are copied verbatim. The tool (os_list_sheet) then compares name, quote, type and
region between E1 and E2 and holds every row where they differ."""
import csv
import os
import re
import sys

import yaml

here = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
L = "pmdc-colleges-with-hospitals.csv"
N_CHECKED, N_MATCHED = 88, 74  # FU-15: both checks judged 88 rows and matched 74


def load(name):
    return yaml.safe_load(open(os.path.join(here, name), encoding="utf-8"))


types = load("section-types.yaml")
words = load("region-words.yaml")
pat = {w: re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])") for w in words}

# --- the PBS district/division table and the two checks (FU-15) ---
table = load("district-regions.yaml")
c1, c2 = load("checks/district-check1.yaml"), load("checks/district-check2.yaml")
if [x["ref"] for x in table["checks"]] != [c1["ref"], c2["ref"]] \
        or (c1["ref"], c2["ref"]) != ("claude-fu15-district-check-1", "claude-fu15-district-check-2"):
    raise SystemExit("district-regions.yaml `checks` are not claude-fu15-district-check-1 and -2")
units = {(u["name"], u["unit"], u["region"], u["doc"], u["page"]) for u in table["units"]}
t1 = {(d["district"], "district", d["region"], d["doc"], d["page"]) for d in c1["district_table"]} \
    | {(d["division"], "division", d["region"], d["doc"], d["page"]) for d in c1["extended_rule"]["division_table"]}
t2 = {(d["name"], d["type"], d["region"], d["doc"], d["page"]) for d in c2["unit_table"]}
if len(table["units"]) != len(units) or units != t1 or units != t2:
    raise SystemExit(f"district-regions.yaml units differ from the checks: {sorted(units ^ t1)} / {sorted(units ^ t2)}")
docs = {(d["url"], d["sha256"], d["region"]) for d in table["source"]["documents"]}
if docs != {(d["url"], d["sha256"], d["region"]) for d in c1["source"]["documents"]} \
        or docs != {(d["url"], d["sha256"], d["region"]) for d in c2["source"]["documents"]}:
    raise SystemExit("district-regions.yaml source documents differ from the checks")
if any(u[3] not in {d[0].rsplit("/", 1)[1] for d in docs if d[2] == u[2]} for u in units):
    raise SystemExit("a unit's doc is not the file of its region")


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]", " ", s.lower())).strip()


by_name = {}  # normalised name -> {(printed name, region)}
for n, _, r, _, _ in units:
    by_name.setdefault(norm(n), set()).add((n, r))
by_space_free = {}
for k in by_name:
    by_space_free.setdefault(k.replace(" ", ""), set()).add(k)


def district(text):
    """(printed unit name, region, form) for the last comma part of `text`, or None."""
    k = norm(text.split(",")[-1])
    form = "exact"
    if k not in by_name:
        hits = by_space_free.get(k.replace(" ", ""), set())
        if len(hits) != 1:
            return None
        k, form = next(iter(hits)), "space_free"
    hit = by_name[k]
    if len({r for _, r in hit}) != 1:  # a name printed in two regions never matches
        return None
    return next(iter(hit))[0], next(iter(hit))[1], form


# each check's per-row result: key -> (address, unit name or None, region or None)
r1 = {}
for x in c1["rows"]:
    r1[x["row_id"]] = [x["address"], x.get("district"), x.get("region")]
for x in c1["extended_rule"]["rows"]:  # the 45 rows check 1 rejudged under the extended rule
    if x["row_id"] not in r1 or r1[x["row_id"]][1] is not None:
        raise SystemExit(f"check 1 extended_rule row {x['row_id']} was not unmatched under the strict rule")
    r1[x["row_id"]][1:] = [x.get("unit_name"), x.get("region")] if x["status"] == "matched" else [None, None]
r2 = {x["row_id"]: [x["address"], x.get("matched_name"), x.get("region")] for x in c2["rows"]}
if set(r1) != set(r2):
    raise SystemExit(f"the checks judged different rows: {sorted(set(r1) ^ set(r2))}")
for k in r1:
    if r1[k] != r2[k]:
        raise SystemExit(f"{k}: check 1 {r1[k]} and check 2 {r2[k]} differ")
checked = {int(k.rsplit("-", 1)[1]): v for k, v in r1.items()}

for x in ("E1", "E2"):
    rows = list(csv.DictReader(open(os.path.join(here, "source-extractions", x, L), encoding="utf-8", newline="")))
    got = {}
    with open(os.path.join(here, x, L), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["key", "name", "quote", "type", "region", "page", "doc_sha256"])
        for r in rows:
            if r["section"] not in types:
                raise SystemExit(f"{x} key {r['key']}: section '{r['section']}' is not in section-types.yaml")
            text = r["address"] if r["address"].strip() else r["name"]
            found = {words[k] for k, p in pat.items() if p.search(text)}
            if len(found) > 1:
                raise SystemExit(f"{x} key {r['key']}: more than one region word in '{text}'")
            region = found.pop() if found else ""
            key = int(r["key"])
            if key in checked:
                if region:
                    raise SystemExit(f"{x} key {key}: judged by the district checks but has a province word")
                if text != checked[key][0]:
                    raise SystemExit(f"{x} key {key}: text '{text}' is not the checks' address '{checked[key][0]}'")
                hit = district(text)
                got[key] = (hit[0], hit[1]) if hit else (None, None)
                if hit:
                    region = hit[1]
            w.writerow([r["key"], r["name"], r["quote"], types[r["section"]], region, r["page"], r["doc_sha256"]])
    if set(got) != set(checked):
        raise SystemExit(f"{x}: checked rows missing from the extraction: {sorted(set(checked) - set(got))}")
    diff = sorted(k for k in got if got[k] != tuple(checked[k][1:]))
    if diff:
        raise SystemExit(f"{x}: the district step differs from both checks on {diff}")
    if sum(1 for v in got.values() if v[1]) != N_MATCHED or len(got) != N_CHECKED:
        raise SystemExit(f"{x}: {sum(1 for v in got.values() if v[1])} of {len(got)} matched; the ruling is "
                         f"{N_MATCHED} of {N_CHECKED}")
    by_region = {}
    for k, (_, reg) in got.items():
        if reg:
            by_region[reg] = by_region.get(reg, 0) + 1
    print(f"wrote {x}/{L}: {len(rows)} rows; district step: {sum(by_region.values())} of {len(got)} checked rows "
          f"matched {dict(sorted(by_region.items()))}; unmatched {sorted(k for k, v in got.items() if not v[1])}")
