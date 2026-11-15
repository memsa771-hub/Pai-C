"""Controller derivation (W12 D-PMDC, 2026-11-15, for the owner to confirm). Run from this folder or anywhere:
    python -I derive.py <this folder>
For BOTH extractions alike, from source-extractions/E1 and E2 (the agents' CSVs, unchanged), it writes E1/ and E2/ with
the columns key, name, quote, type, region, page, doc_sha256. Only two columns are added; nothing else is changed:
- type = section-types.yaml[section] (ruling 1). An unknown section stops the script.
- region = region-words.yaml[word] for the province/territory word printed in the row's address (ruling 2). The address
  is the extraction's own `address` cell; where an extraction left it empty (its whole cell is in `name`), the `name`
  cell is scanned instead. The bold remark "(Letter sent to M/o NHSR&C, Islamabad ...)" is in neither cell (both
  extractions keep it in `quote` only), so it never gives a region; a word inside the college name before the address
  (168 "Sindh Medical College", 187 "Sindh Institute ...") is not used. No region from a city. Two different words in
  one row stop the script.
key, name, quote, page and doc_sha256 are copied verbatim. The tool (os_list_sheet) then compares name, quote, type and
region between E1 and E2 and holds every row where they differ."""
import csv
import os
import re
import sys

import yaml

here = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
L = "pmdc-colleges-with-hospitals.csv"
types = yaml.safe_load(open(os.path.join(here, "section-types.yaml"), encoding="utf-8"))
words = yaml.safe_load(open(os.path.join(here, "region-words.yaml"), encoding="utf-8"))
pat = {w: re.compile(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])") for w in words}
for x in ("E1", "E2"):
    rows = list(csv.DictReader(open(os.path.join(here, "source-extractions", x, L), encoding="utf-8", newline="")))
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
            w.writerow([r["key"], r["name"], r["quote"], types[r["section"]], found.pop() if found else "",
                        r["page"], r["doc_sha256"]])
    print(f"wrote {x}/{L}: {len(rows)} rows")
