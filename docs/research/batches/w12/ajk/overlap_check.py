"""Mechanical name match: every AJK HED college name against batch 1-5 v4 and other W12 Institutions rows."""
import csv, glob, os, re, sys
import openpyxl

repo, ajk = sys.argv[1], sys.argv[2]
GENERIC = {"govt", "government", "college", "colleges", "boys", "girls", "for", "the", "of", "degree", "inter",
           "intermediate", "post", "graduate", "postgraduate", "model", "science", "and", "women", "men", "&",
           "public", "school", "university", "institute", "ajk", "aj&k", "azad", "jammu", "kashmir", "pakistan",
           "campus", "elementary", "higher", "secondary", "education", "cadet", "commerce", "technology"}


def toks(s):
    s = re.sub(r"[^a-z0-9& ]+", " ", (s or "").casefold())
    return [t for t in s.split() if t]


def norm(s):
    return " ".join(toks(s))


targets = []
files = sorted(glob.glob(os.path.join(repo, "docs/research/batches/PAI-Research-Batch[1-5]-*-v4.xlsx"))) + \
    sorted(glob.glob(os.path.join(repo, "docs/research/batches/PAI-Research-W12-*.xlsx")))
for f in files:
    wb = openpyxl.load_workbook(f, read_only=True)
    if "Institutions" not in wb.sheetnames:
        continue
    rows = wb["Institutions"].iter_rows(values_only=True)
    hdr = None
    for r in rows:
        if r and "inst_id" in r:
            hdr = list(r)
            break
    for r in rows:
        d = dict(zip(hdr, r))
        if d.get("inst_id") and d.get("name"):
            targets.append((os.path.basename(f), str(d["inst_id"]), str(d["name"]), str(d.get("region") or ""),
                            str(d.get("city") or ""), str(d.get("type") or "")))
print("files:", len(files), "target rows:", len(targets))
for f in files:
    print("  ", os.path.basename(f))

ajk_rows = []
for f in sorted(glob.glob(os.path.join(ajk, "E1", "*.csv"))):
    for r in csv.DictReader(open(f, encoding="utf-8")):
        ajk_rows.append((os.path.basename(f).replace(".csv", ""), r["key"], r["name"]))
print("ajk rows:", len(ajk_rows))

exact, place = [], []
tnorm = [(t, norm(t[2]), set(toks(t[2])) - GENERIC) for t in targets]
for lst, k, name in ajk_rows:
    n, dist = norm(name), set(toks(name)) - GENERIC
    for t, tn, td in tnorm:
        if n == tn:
            exact.append((lst, k, name, t))
        elif dist and dist <= td and ("college" in tn or "school" in tn or "institute" in tn):
            place.append((lst, k, name, t))
print("\nEXACT normalised-name matches:", len(exact))
for e in exact:
    print(" ", e)
print("\nDistinctive-token matches (all of the AJK row's non-generic tokens appear in the target name):", len(place))
for e in place:
    print(" ", e)
print("\nAll AJK-region target rows (region contains 'jammu' or 'ajk'):")
for t in targets:
    if re.search(r"jammu|ajk|aj&k|kashmir", (t[3] + " " + t[2]).casefold()):
        print(" ", t)
