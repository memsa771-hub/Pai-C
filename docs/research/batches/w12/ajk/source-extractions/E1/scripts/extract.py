"""E1 extractor for D-AJK: stdlib html.parser walking table rows.
Usage: python -I extract.py <raw_dir> <out_dir>
"""
import csv, hashlib, json, os, re, sys
from html.parser import HTMLParser

LISTS = [
    ("ajk-hed-postgraduate-colleges", "post-graduate-colleges.html", 14),
    ("ajk-hed-degree-colleges", "degree-colleges.html", 75),
    ("ajk-hed-model-science-colleges", "model-science-colleges.html", 7),
    ("ajk-hed-inter-colleges", "inter-colleges.html", 81),
]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
HIDE_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|(left|top|right|text-indent)\s*:\s*-\d{3,}|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d])", re.I)


def hidden_attr(attrs):
    d = dict(attrs)
    cls = (d.get("class") or "").split()
    if "hidden" in cls or "hidden" in d or d.get("aria-hidden") == "true":
        return True
    return bool(HIDE_STYLE.search(d.get("style") or ""))


class RowWalker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, hidden)
        self.rows = []   # dicts: cells, hidden, table_index, line
        self.table_count = 0
        self.table_idx = []
        self.cur_row = None
        self.cur_cell = None

    def hidden_now(self):
        return any(h for _, h in self.stack)

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if tag == "br" and self.cur_cell is not None:
                self.cur_cell.append(" ")
            return
        self.stack.append((tag, hidden_attr(attrs)))
        if tag == "table":
            self.table_count += 1
            self.table_idx.append(self.table_count)
        elif tag == "tr":
            self.cur_row = {"cells": [], "hidden": self.hidden_now(),
                            "table": self.table_idx[-1] if self.table_idx else None,
                            "line": self.getpos()[0]}
        elif tag in ("td", "th") and self.cur_row is not None:
            self.cur_cell = []

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and self.cur_cell is not None:
            self.cur_cell.append(" ")

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # pop to matching tag
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in ("td", "th") and self.cur_cell is not None and self.cur_row is not None:
            self.cur_row["cells"].append("".join(self.cur_cell))
            self.cur_cell = None
        elif tag == "tr" and self.cur_row is not None:
            self.rows.append(self.cur_row)
            self.cur_row = None
        elif tag == "table" and self.table_idx:
            self.table_idx.pop()

    def handle_data(self, data):
        if self.cur_cell is not None:
            self.cur_cell.append(data)


def ws(s):
    return " ".join(s.split())


def main(raw_dir, out_dir):
    report = {}
    for list_id, fname, expected in LISTS:
        raw = open(os.path.join(raw_dir, fname), "rb").read()
        sha = hashlib.sha256(raw).hexdigest()
        p = RowWalker()
        p.feed(raw.decode("utf-8"))
        p.close()
        data, skipped = [], []
        for r in p.rows:
            cells = [ws(c) for c in r["cells"]]
            if len(cells) == 2 and re.fullmatch(r"\d+", cells[0]):
                if r["hidden"]:
                    skipped.append({"reason": "hidden ancestor", **r})
                    continue
                data.append((cells[0], cells[1], r["table"], r["line"]))
            else:
                skipped.append({"reason": "not a serial/name row", "cells": cells, "table": r["table"], "line": r["line"]})
        with open(os.path.join(out_dir, list_id + ".csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["key", "name", "quote", "city", "page", "doc_sha256"])
            for key, name, _, _ in data:
                w.writerow([key, name, f"{key} | {name}", "", "", sha])
        serials = [int(k) for k, _, _, _ in data]
        report[list_id] = {
            "file": fname, "sha256": sha, "rows": len(data), "expected": expected,
            "count_ok": len(data) == expected,
            "serials_ok": serials == list(range(1, len(serials) + 1)),
            "empty_names": [k for k, n, _, _ in data if not n],
            "tables_used": sorted({t for _, _, t, _ in data}),
            "hidden_rows": sum(1 for r in p.rows if r["hidden"]),
            "skipped": skipped,
        }
    json.dump(report, open(os.path.join(out_dir, "check.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    for k, v in report.items():
        print(k, v["rows"], v["expected"], v["count_ok"], v["serials_ok"], v["empty_names"], v["tables_used"], v["hidden_rows"], len(v["skipped"]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
