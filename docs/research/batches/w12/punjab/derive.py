"""Controller derivation (W12 D-PUNJAB, 2026-11-15). E1's attribute columns drift in the PDF text layer, so its
quote cannot be compared with E2's. For both extractions alike: quote = "<key> | <name>" (name only for GRW and MUL, which print no serial) built from that
extraction's OWN key and name (verbatim cells); city kept only where BOTH extractions have a non-empty city
(compared later by the tool). Nothing else changes; doc_sha256, key, name, page are copied as they are."""
import csv, sys, glob, os
src, dst = sys.argv[1], sys.argv[2]
for f in sorted(glob.glob(os.path.join(src, 'E1', '*.csv'))):
    L = os.path.basename(f)
    e = {x: {r['key']: r for r in csv.DictReader(open(os.path.join(src, x, L), encoding='utf-8'))} for x in ('E1', 'E2')}
    for x in ('E1', 'E2'):
        other = 'E2' if x == 'E1' else 'E1'
        with open(os.path.join(dst, x + 'q', L), 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh); w.writerow(['key', 'name', 'quote', 'city', 'page', 'doc_sha256'])
            for k, r in e[x].items():
                o = e[other].get(k, {})
                city = r['city'] if (r.get('city') and o.get('city')) else ''
                q = r["name"] if L.endswith(("-grw.csv", "-mul.csv")) else f"{k} | {r['name']}"
                w.writerow([k, r["name"], q, city, r.get('page', ''), r['doc_sha256']])
