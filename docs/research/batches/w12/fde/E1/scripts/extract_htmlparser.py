"""E1 extractor: stdlib html.parser. Usage: python -I extract_htmlparser.py OUT.csv PAGE.html [PAGE.html ...]"""
import sys, csv, hashlib, re
from html.parser import HTMLParser

class T(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_tbody = False; self.row = None; self.cell = None
        self.depth_strong = 0; self.in_muted = False
        self.rows = []; self.hidden = []; self.comments = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        st = (a.get('style') or '').replace(' ', '').lower()
        if 'hidden' in a or 'display:none' in st or 'visibility:hidden' in st or a.get('aria-hidden') == 'true':
            self.hidden.append((tag, attrs, self.getpos()))
        if tag == 'tbody': self.in_tbody = True
        elif self.in_tbody and tag == 'tr': self.row = []
        elif self.row is not None and tag == 'td':
            self.cell = {'text': [], 'strong': [], 'muted': [], 'tags': []}
        elif self.cell is not None:
            self.cell['tags'].append(tag)
            if tag == 'strong': self.depth_strong += 1
            if tag == 'span' and 'u-muted' in (a.get('class') or '').split(): self.in_muted = True
    def handle_endtag(self, tag):
        if tag == 'tbody': self.in_tbody = False
        elif tag == 'tr' and self.row is not None: self.rows.append(self.row); self.row = None
        elif tag == 'td' and self.cell is not None: self.row.append(self.cell); self.cell = None
        elif self.cell is not None:
            if tag == 'strong': self.depth_strong -= 1
            if tag == 'span': self.in_muted = False
    def handle_data(self, d):
        if self.cell is None: return
        self.cell['text'].append(d)
        if self.depth_strong: self.cell['strong'].append(d)
        if self.in_muted: self.cell['muted'].append(d)
    def handle_comment(self, d): self.comments.append((d, self.getpos()))

def ws(s): return re.sub(r'\s+', ' ', ''.join(s)).strip()

out = sys.argv[1]; rows = []; problems = []
for path in sys.argv[2:]:
    raw = open(path, 'rb').read(); sha = hashlib.sha256(raw).hexdigest()
    p = T(); p.feed(raw.decode('utf-8')); p.close()
    print(f'{path}: sha256={sha} tbody_rows={len(p.rows)} hidden_elems={len(p.hidden)} comments={len(p.comments)}')
    for h in p.hidden: print('  HIDDEN', h)
    for c in p.comments: print('  COMMENT', repr(c[0][:120]), c[1])
    for r in p.rows:
        if len(r) != 5: problems.append(f'{path}: row with {len(r)} cells'); continue
        key = ws(r[0]['text']); name = ws(r[2]['strong']); addr = ws(r[2]['muted'])
        extra = set(r[2]['tags']) - {'a', 'strong', 'br', 'span'}
        if extra: problems.append(f'{path}: key {key} unexpected tags {extra}')
        q = f'{key} | {name}' + (f' | {addr}' if addr else '')
        rows.append({'key': key, 'name': name, 'quote': q, 'city': '', 'page': '', 'doc_sha256': sha})
keys = [r['key'] for r in rows]
print('rows', len(rows), 'unique keys', len(set(keys)), 'empty names', sum(1 for r in rows if not r['name']),
      'keys numeric 1..N contiguous', sorted(int(k) for k in keys) == list(range(1, len(keys)+1)),
      'page order == key order', keys == [str(i) for i in range(1, len(keys)+1)],
      'with address', sum(1 for r in rows if r['quote'].count(' | ') == 2))
for pr in problems: print('PROBLEM', pr)
with open(out, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['key','name','quote','city','page','doc_sha256']); w.writeheader(); w.writerows(rows)
