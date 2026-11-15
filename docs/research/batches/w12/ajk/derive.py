"""Controller derivation (W12 D-AJK, 2026-11-15, for the owner to confirm). Run in Docker:
    python -I derive.py <this folder>
The two raw pages of each list differ only in Cloudflare's per-request email-protection attribute in the footer
(`data-cfemail="<hex>"`), so their sha256s differ. The ruling: the document identity is the sha256 of the raw page with
every `data-cfemail="<hex>"` value replaced by `data-cfemail=""`.

For BOTH extractions alike, from source-extractions/E1 and E2 (the agents' files, unchanged), it writes E1/ and E2/:
- each row's doc_sha256 must be the sha256 of that extraction's OWN raw page (or the script stops);
- doc_sha256 is set to the normalised sha256 of that same raw page.
Nothing else is changed: the other cells, the header, the column order and the CSV dialect are kept. The script checks
that the source CSV re-serialises to its exact bytes before it writes anything."""
import csv
import hashlib
import io
import os
import re
import sys

here = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
RAW = {"ajk-hed-postgraduate-colleges.csv": "post-graduate-colleges.html",
       "ajk-hed-degree-colleges.csv": "degree-colleges.html",
       "ajk-hed-model-science-colleges.csv": "model-science-colleges.html",
       "ajk-hed-inter-colleges.csv": "inter-colleges.html"}
CFEMAIL = re.compile(rb'data-cfemail="[0-9A-Fa-f]*"')


def serialise(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")  # both agents wrote CRLF (the csv module default)
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


for x in ("E1", "E2"):
    for name, raw_name in RAW.items():
        raw = open(os.path.join(here, "source-extractions", x, "raw", raw_name), "rb").read()
        raw_sha = hashlib.sha256(raw).hexdigest()
        blanked, n = CFEMAIL.subn(b'data-cfemail=""', raw)
        if n == 0:
            raise SystemExit(f"{x} {raw_name}: no data-cfemail attribute")
        norm_sha = hashlib.sha256(blanked).hexdigest()
        src = open(os.path.join(here, "source-extractions", x, name), "rb").read()
        table = list(csv.reader(io.StringIO(src.decode("utf-8"), newline="")))
        header, rows = table[0], table[1:]
        if serialise(header, rows) != src:
            raise SystemExit(f"{x} {name}: the CSV does not re-serialise to its own bytes")
        i = header.index("doc_sha256")
        for r in rows:
            if r[i] != raw_sha:
                raise SystemExit(f"{x} {name} key {r[0]}: doc_sha256 {r[i]} is not its raw page's sha256 {raw_sha}")
            r[i] = norm_sha
        open(os.path.join(here, x, name), "wb").write(serialise(header, rows))
        print(f"{x} {name}: {len(rows)} rows; raw {raw_sha}; {n} data-cfemail blanked; doc_sha256 {norm_sha}")
