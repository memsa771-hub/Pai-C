#!/usr/bin/env python3
"""Compare two counselor_deep replay JSON files (stdlib only).

Usage: python docs/connect/replays/compare.py BEFORE.json AFTER.json

Prints a warning line first if the two files' policy_mode/mode differ.
Exit code: 0 whether or not there are differences, 2 on bad usage.
Prints a markdown table of every persona turn whose reply, action.type,
action_status, decision or guard_violations differ, plus persona
status/stop_reason changes. Prints "No differences." when none.
Ids, timings, usage and cost are ignored.
"""
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value).replace("|", "\\|").replace("\n", " ")


def turn_fields(turn):
    action = turn.get("action") or {}
    return {
        "reply": turn.get("reply"),
        "action.type": action.get("type") if isinstance(action, dict) else action,
        "action_status": turn.get("action_status"),
        "decision": turn.get("decision"),
        "guard_violations": turn.get("guard_violations"),
    }


def compare(before, after):
    rows = []
    bp = {p.get("persona"): p for p in before.get("personas", [])}
    ap = {p.get("persona"): p for p in after.get("personas", [])}
    for name in sorted(set(bp) | set(ap), key=str):
        if name not in bp or name not in ap:
            rows.append((name, "-", "persona", "present" if name in bp else "only in AFTER",
                         "present" if name in ap else "only in BEFORE"))
            continue
        b, a = bp[name], ap[name]
        for key in ("status", "stop_reason"):
            if b.get(key) != a.get(key):
                rows.append((name, "-", key, b.get(key), a.get(key)))
        bt = {t.get("turn"): t for t in b.get("turns", [])}
        at = {t.get("turn"): t for t in a.get("turns", [])}
        for n in sorted(set(bt) | set(at), key=lambda x: (x is None, x)):
            if n not in bt or n not in at:
                rows.append((name, n, "turn", "present" if n in bt else "only in AFTER",
                             "present" if n in at else "only in BEFORE"))
                continue
            fb, fa = turn_fields(bt[n]), turn_fields(at[n])
            for field in fb:
                if fb[field] != fa[field]:
                    rows.append((name, n, field, fb[field], fa[field]))
    return rows


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    before, after = load(argv[1]), load(argv[2])
    for key in ("mode", "policy_mode"):
        if before.get(key) != after.get(key):
            print(f"Warning: comparing {key} {before.get(key)} with {after.get(key)}")
            print()
    rows = compare(before, after)
    if not rows:
        print("No differences.")
        return 0
    print("| persona | turn | field | before | after |")
    print("|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(cell(c) for c in row) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
