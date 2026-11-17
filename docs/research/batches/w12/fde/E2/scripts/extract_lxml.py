"""E2 extractor for fde-hssc-participating-colleges: lxml XPath.

Usage: python -I extract_lxml.py <main_html> <out_csv> [<crosscheck_html> ...]
Reads the per=200 page (all rows). Optional extra pages (default view page 1 and 2)
are parsed the same way and compared row-for-row against the main page.
"""
import csv
import hashlib
import re
import sys

from lxml import html


def norm(s):
    # collapse whitespace only; no other change to the printed text
    return re.sub(r"\s+", " ", s).strip()


def parse(path):
    raw = open(path, "rb").read()
    sha = hashlib.sha256(raw).hexdigest()
    doc = html.fromstring(raw.decode("utf-8"))
    tables = doc.xpath("//table")
    headers = [norm(t.text_content()) for t in doc.xpath("//table[1]/thead/tr/th")]
    rows = []
    for tr in doc.xpath("//table[1]/tbody/tr"):
        tds = tr.xpath("./td")
        if len(tds) != 5:
            rows.append({"error": "td count %d" % len(tds), "text": norm(tr.text_content())})
            continue
        key = norm(tds[0].text_content())
        code = norm(tds[1].text_content())
        names = tds[2].xpath(".//strong")
        name = norm(names[0].text_content()) if names else ""
        addr_nodes = tds[2].xpath(".//span[contains(concat(' ', normalize-space(@class), ' '), ' u-muted ')]")
        addr = norm(addr_nodes[0].text_content()) if addr_nodes else ""
        href = tds[2].xpath(".//a/@href")
        rows.append({
            "key": key, "code": code, "name": name, "addr": addr,
            "n_strong": len(names), "n_addr": len(addr_nodes),
            "href": href[0] if href else "",
            "phone": norm(tds[3].text_content()),
            "loc": norm(tds[4].text_content()),
        })
    summary = norm(" ".join(doc.xpath("//p[contains(@class,'c-pagination__summary')]//text()")))
    return sha, rows, headers, len(tables), summary, doc


def main():
    main_path, out_csv = sys.argv[1], sys.argv[2]
    sha, rows, headers, ntables, summary, doc = parse(main_path)
    print("main sha256", sha)
    print("tables", ntables, "headers", headers, "summary", repr(summary))
    problems = []
    errs = [r for r in rows if "error" in r]
    if errs:
        problems.append("bad rows: %r" % errs)
    good = [r for r in rows if "error" not in r]
    if len(good) != 82:
        problems.append("row count %d != 82" % len(good))
    keys = [r["key"] for r in good]
    if len(set(keys)) != len(keys):
        problems.append("duplicate keys")
    if [int(k) for k in keys] != list(range(1, len(keys) + 1)):
        problems.append("keys not 1..N in order")
    for r in good:
        if not r["name"]:
            problems.append("empty name at key %s" % r["key"])
        if r["n_strong"] != 1 or r["n_addr"] > 1:
            problems.append("odd cell at key %s: strong=%d addr=%d" % (r["key"], r["n_strong"], r["n_addr"]))
    # hidden / injected content checks
    hidden = doc.xpath("//*[@hidden or contains(translate(@style,' ',''),'display:none') "
                       "or contains(translate(@style,' ',''),'visibility:hidden') or @aria-hidden='true']")
    print("hidden-styled elements:", [(h.tag, h.get("class"), norm(h.text_content())[:60]) for h in hidden])
    print("scripts:", [s.get("src") or norm(s.text_content())[:80] for s in doc.xpath("//script")])
    print("iframes:", len(doc.xpath("//iframe")), "inline style tags:", len(doc.xpath("//style")))
    print("comments:", [norm(c.text)[:80] for c in doc.xpath("//comment()")])
    tbody_text_nodes = doc.xpath("//table[1]/tbody//text()[normalize-space()]")
    print("tbody non-blank text nodes:", len(tbody_text_nodes))

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["key", "name", "quote", "city", "page", "doc_sha256"])
        for r in good:
            quote = "%s | %s" % (r["key"], r["name"])
            if r["addr"]:
                quote += " | %s" % r["addr"]
            w.writerow([r["key"], r["name"], quote, "", "", sha])
    print("wrote", len(good), "rows")
    print("rows with address line:", sum(1 for r in good if r["addr"]))
    print("rows without link:", [r["key"] for r in good if not r["href"]])

    # cross-check against default-view pages
    if len(sys.argv) > 3:
        other = []
        for p in sys.argv[3:]:
            s2, r2, _, _, sm2, _ = parse(p)
            print("crosscheck", p, s2, "rows", len(r2), "summary", repr(sm2))
            other.extend(r2)
        same = [(a["key"], a["name"], a["addr"]) for a in good] == [(b.get("key"), b.get("name"), b.get("addr")) for b in other]
        print("default pages 1+2 identical to per=200 (key,name,addr):", same)
        if not same:
            problems.append("default-view pages differ from per=200")

    # odd rows report
    for r in good:
        if r["name"] != r["name"].strip() or "  " in r["name"]:
            print("odd spacing", r["key"])
        if r["addr"] and r["addr"] == r["name"]:
            print("addr equals name at key", r["key"])
    print("PROBLEMS:", problems or "none")


if __name__ == "__main__":
    main()
