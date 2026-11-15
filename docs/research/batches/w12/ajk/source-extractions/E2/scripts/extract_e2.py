"""E2 extractor for D-AJK: lxml XPath over table cells.
Usage: python -I extract_e2.py <raw_dir> <out_dir>
"""
import csv, hashlib, json, re, sys
from pathlib import Path
from lxml import html as LH

LISTS = [
    ("ajk-hed-postgraduate-colleges", "post-graduate-colleges.html", 14),
    ("ajk-hed-degree-colleges", "degree-colleges.html", 75),
    ("ajk-hed-model-science-colleges", "model-science-colleges.html", 7),
    ("ajk-hed-inter-colleges", "inter-colleges.html", 81),
]
HIDE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?![.\d])|"
                  r"(left|top|right|text-indent)\s*:\s*-\d|font-size\s*:\s*0(?![.\d])|"
                  r"(^|;)\s*(height|width)\s*:\s*0(px)?\s*(;|$)|clip\s*:", re.I)
WS = re.compile(r"\s+")


def collapse(s):
    return WS.sub(" ", s).strip()


def hidden_ancestry(el):
    out = []
    for a in [el] + list(el.iterancestors()):
        st = a.get("style") or ""
        cl = (a.get("class") or "").split()
        if HIDE.search(st) or "hidden" in cl or a.get("hidden") is not None or a.get("aria-hidden") == "true":
            out.append(f"<{a.tag} class='{a.get('class')}' style='{st}'>")
    return out


def main(raw_dir, out_dir):
    raw_dir, out_dir = Path(raw_dir), Path(out_dir)
    report = {}
    for list_id, fname, expected in LISTS:
        data = (raw_dir / fname).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        doc = LH.fromstring(data.decode("utf-8"))
        all_tables = doc.xpath("//table")
        # The data table(s): tables inside the page content (main), not the notification bar.
        rows = doc.xpath("//main//table[not(@id='wpfront-notification-bar-table')]//tr[td]")
        out_rows, problems = [], []
        for tr in rows:
            tds = tr.xpath("./td")
            cells = [collapse(td.text_content()) for td in tds]
            if len(cells) != 2:
                problems.append(f"row with {len(cells)} cells: {cells}")
                continue
            serial, name = cells
            hid = hidden_ancestry(tr)
            if hid:
                problems.append(f"row {serial} under hidden markup: {hid}")
                continue
            links = tr.xpath(".//a/@href")
            if links:
                problems.append(f"row {serial} contains links {links}")
            out_rows.append((serial, name))
        serials = [r[0] for r in out_rows]
        if len(out_rows) != expected:
            problems.append(f"row count {len(out_rows)} != expected {expected}")
        if serials != [str(i) for i in range(1, len(out_rows) + 1)]:
            problems.append(f"serials not 1..N: {serials}")
        for s, n in out_rows:
            if not n:
                problems.append(f"empty name at serial {s}")
        with open(out_dir / f"{list_id}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "name", "quote", "city", "page", "doc_sha256"])
            for s, n in out_rows:
                w.writerow([s, n, f"{s} | {n}", "", "", sha])
        report[list_id] = {"file": fname, "sha256": sha, "tables_in_doc": len(all_tables),
                           "rows": len(out_rows), "expected": expected, "problems": problems}
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
