"""Build an Institutions workbook in the one research format for one official list, from two independent extractions of
the list's document (P2 spec §4.6; master R-35a, R-67, R-68). Nothing is fetched, parsed from the web or invented: the
tool only combines the two CSVs and the list's own data.

    python -m scripts.os_list_sheet --lists DIR --list LIST_ID --country CODE --e1 E1.csv --e2 E2.csv \\
        --e1-method TEXT --e2-method TEXT --mapping MAP.yaml --checker1 REF DATE --checker2 REF DATE --out OUT.xlsx \
        [--allow-count-mismatch] [--identical-extractions REASON] [--force]

`--lists DIR` holds the official-list files (the H3 shape); the list's url, region, family, institution_type, row_count
and count_confirmed come from there (`--country` is the key of regions.yaml the file is read with). E1 and E2 each have
the columns key, name, quote and doc_sha256, and optionally city and page (and any column the mapping names). The
mapping (data) gives:

    id_prefix: <text>            # inst_id = id_prefix + key
    type: <a type of format.yaml type_kinds>      # must be the list's institution_type; or
    type_column: <CSV column holding each row's type>
    region: list                 # the list file's region; or `column` with region_column: <CSV column>
    city_column: <CSV column>    # optional
    read_method: <text>          # must map to `fetch` in format.yaml
    retrieved: YYYY-MM-DD        # the day the document both extractions read was downloaded

Rules: E1 and E2 are two different files (not the same bytes, unless `--identical-extractions REASON` is recorded) made
by two different methods (`--e1-method`, `--e2-method`); they must name the same documents (doc_sha256, 64 hex) and each
must hold the list's row_count rows (`--allow-count-mismatch` only when the list's count is not confirmed; its use is
recorded). Rows are matched by key and
compared after normalising (casefold, whitespace collapsed, quotes and dashes unified); the normalising is for the
comparison only, the cells written are E1's verbatim text. A row the two agree on is written with check 1 `correct` and
check 2 `yes` by the two checker refs; any other row goes to `<out stem>.held.csv` with its reason and is not written.
The workbook gets a "Derived from" sheet (each input's sha256, the methods, the list's type and, with type_column, the
rows per type, any override and the command). Formula-like cells are neutralised. Every check runs before anything is
written; an existing output is refused unless `--force`. Exit code 2 when refused.
"""

import argparse
import csv
import re
import shlex
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

from app.os.knowledge.review.reviewers import REF
from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.reader import file_sha256
from app.os.knowledge.sheets.safe import safe_cell
from app.os.knowledge.sheets.template import write_workbook
from app.os.registry.lists import OfficialListError, parse_official_lists
from app.os.registry.model import slug

PROVENANCE_SHEET = "Derived from"
LIST_KINDS = ("institution", "campus")  # the registry kinds that join an official list
REQUIRED = ("key", "name", "quote", "doc_sha256")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
HELD_COLUMNS = ["key", "inst_id", "reason", "detail", "e1_name", "e2_name", "e1_quote", "e2_quote"]

_QUOTES = str.maketrans({c: "'" for c in "‘’‚‛′´`"}
                        | {c: '"' for c in "“”„‟″«»"})
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−﹘﹣－"})


class Refused(ValueError):
    pass


def norm(text: str | None) -> str:
    """The comparison form of a cell: casefold, whitespace collapsed, quotes and dashes unified. Never written."""
    t = (text or "").translate(_QUOTES).translate(_DASHES).casefold()
    return re.sub(r"\s+", " ", t).strip()


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames or []), list(r)


def _day(text: str, what: str) -> str:
    try:
        return date.fromisoformat(str(text).strip()).isoformat()
    except ValueError as e:
        raise Refused(f"{what}: '{text}' is not a date (YYYY-MM-DD)") from e


def _find_list(directory: Path, list_id: str, country: str) -> tuple[Path, str, object]:
    """(the list file, its region as written, the parsed list entry)."""
    want = f"list:{slug(list_id)}"
    found = []
    for f in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8"))
            entries = parse_official_lists(data, country=country)
        except (yaml.YAMLError, OfficialListError) as e:
            raise Refused(f"list file {f.name}: {e}") from e
        for e in entries:
            if e.entity_id == want:
                found.append((f, str(data["region"]), e))
    if len(found) != 1:
        raise Refused(f"list '{list_id}': {'not in' if not found else 'more than once in'} {directory}")
    return found[0]


def build(*, lists: Path, list_id: str, country: str, e1: Path, e2: Path, mapping_path: Path,
          checker1: tuple[str, str], checker2: tuple[str, str], out: Path, allow_count_mismatch: bool,
          command: str, e1_method: str = "", e2_method: str = "", identical_reason: str | None = None,
          force: bool = False) -> dict:
    """Write the workbook and the held CSV; return the report. Every check runs before anything is written, so a
    refused run writes nothing; an existing output is refused unless `force`, which removes it first."""
    fmt = load_format()
    held_path = out.with_name(out.stem + ".held.csv")
    inputs = [e1, e2, mapping_path]
    if {out.resolve(), held_path.resolve()} & {p.resolve() for p in inputs}:
        raise Refused("the outputs must be new files, not inputs")
    if e1.resolve() == e2.resolve():
        raise Refused("E1 and E2 are the same file: two independent extractions are needed")
    existing = [p for p in (out, held_path) if p.exists()]
    if existing and not force:
        raise Refused(f"output exists: {', '.join(p.name for p in existing)} (give --force to overwrite)")
    for p in existing:  # a later refusal must not leave an earlier run's outputs looking like this run's
        p.unlink()
    m1, m2 = (e1_method or "").strip(), (e2_method or "").strip()
    if not m1 or not m2:
        raise Refused("give --e1-method and --e2-method: the extraction method of each CSV")
    if norm(m1) == norm(m2):
        raise Refused(f"E1 and E2 name the same method '{m1}': two different methods are needed")
    identical = None
    if file_sha256(e1) == file_sha256(e2):
        if not (identical_reason or "").strip():
            raise Refused("E1 and E2 have the same sha256: a copy is not a second extraction (give "
                          "--identical-extractions REASON if two methods really gave the same bytes)")
        identical = identical_reason.strip()
    (n1, d1), (n2, d2) = checker1, checker2
    for n in (n1, n2):
        if not REF.match(n):
            raise Refused(f"checker '{n}' is not a reviewer ref (lower-case letters, digits, _ . -)")
    if n1 == n2:
        raise Refused("checker 1 and checker 2 must be different")
    d1, d2 = _day(d1, "checker1 date"), _day(d2, "checker2 date")

    list_file, list_region, entry = _find_list(lists, list_id, country)
    url, row_count = entry.source_url, entry.attrs.get("row_count")
    count_confirmed = bool(entry.attrs.get("count_confirmed"))

    try:
        m = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise Refused(f"mapping {mapping_path.name}: {e}") from e
    if not isinstance(m, dict):
        raise Refused(f"mapping {mapping_path.name}: not a mapping of keys")
    prefix = m.get("id_prefix")
    if not isinstance(prefix, str) or not prefix.strip():
        raise Refused("mapping: id_prefix is required")
    if ("type" in m) == ("type_column" in m):
        raise Refused("mapping: give exactly one of type and type_column")
    if "type" in m:
        t = m["type"]
        if not isinstance(t, str) or fmt.kind_of_type(t) not in LIST_KINDS or t != t.strip().lower():
            raise Refused(f"mapping: type '{t}' is not a type of kind {' or '.join(LIST_KINDS)} in format.yaml")
        if entry.institution_type and t != entry.institution_type:
            raise Refused(f"mapping: type '{t}' is not the list's institution_type '{entry.institution_type}'")
    elif not isinstance(m["type_column"], str) or not m["type_column"].strip():
        raise Refused("mapping: type_column must name a CSV column")
    rule = m.get("region")
    if rule not in ("list", "column") or (rule == "column") != bool(m.get("region_column")):
        raise Refused("mapping: region is `list`, or `column` with region_column")
    read_method = m.get("read_method")
    if not isinstance(read_method, str) or fmt.read_method(read_method) != "fetch" or fmt.is_lead_read(read_method):
        raise Refused(f"mapping: read_method '{read_method}' does not map to fetch in format.yaml")
    retrieved = _day(m.get("retrieved", ""), "mapping retrieved")
    if retrieved > min(d1, d2):
        raise Refused(f"mapping retrieved {retrieved} is after a checker date ({d1}, {d2})")
    columns = [c for c in (m.get("type_column"), m.get("region_column"), m.get("city_column")) if c]

    ext = {}
    for tag, path in (("e1", e1), ("e2", e2)):
        try:
            header, rows = _csv(path)
        except (UnicodeDecodeError, csv.Error) as e:
            raise Refused(f"{tag} {path.name}: not a UTF-8 CSV ({e})") from e
        missing = [c for c in (*REQUIRED, *columns) if c not in header]
        if missing:
            raise Refused(f"{tag} {path.name}: missing column(s) {', '.join(missing)}")
        for line, r in enumerate(rows, start=2):
            if not SHA256.match((r.get("doc_sha256") or "").strip()):
                raise Refused(f"{tag} {path.name} line {line} (key '{(r.get('key') or '').strip()}'): doc_sha256 "
                              f"'{r.get('doc_sha256') or ''}' is not 64 hex characters")
        ext[tag] = rows

    # rule 1: the same documents
    shas = {tag: {r["doc_sha256"].strip().lower() for r in rows} for tag, rows in ext.items()}
    if shas["e1"] != shas["e2"]:
        raise Refused(f"doc_sha256 differs: e1 {sorted(shas['e1'])}, e2 {sorted(shas['e2'])}")
    # rule 2: the list's count
    counts = {tag: len(rows) for tag, rows in ext.items()}
    mismatch = [tag for tag, n in counts.items() if row_count is None or n != row_count]
    override = None
    if mismatch:
        what = f"row_count {row_count}; e1 {counts['e1']} rows, e2 {counts['e2']} rows"
        if not allow_count_mismatch:
            raise Refused(f"count mismatch: {what}")
        if count_confirmed:
            raise Refused(f"count mismatch: {what}; --allow-count-mismatch is only for a list whose count is not "
                          "confirmed")
        override = what

    held: list[dict] = []
    by: dict[str, dict[str, dict]] = {"e1": {}, "e2": {}}
    doubled: set[str] = set()
    for tag, rows in ext.items():
        for line, r in enumerate(rows, start=2):
            k = (r.get("key") or "").strip()
            if not k:
                held.append({"key": "", "reason": f"no_key_{tag}", "detail": f"{tag} line {line}",
                             f"{tag}_name": r.get("name"), f"{tag}_quote": r.get("quote")})
            elif k in by[tag]:
                doubled.add(k)
            else:
                by[tag][k] = r

    def hold(k: str, reason: str, detail: str = "") -> None:
        a, b = by["e1"].get(k) or {}, by["e2"].get(k) or {}
        held.append({"key": k, "inst_id": prefix + k, "reason": reason, "detail": detail,
                     "e1_name": a.get("name"), "e2_name": b.get("name"), "e1_quote": a.get("quote"),
                     "e2_quote": b.get("quote")})

    written: list[dict] = []
    reasons: Counter = Counter()
    types: Counter = Counter()
    for k in dict.fromkeys([*by["e1"], *by["e2"]]):
        a, b = by["e1"].get(k), by["e2"].get(k)
        if k in doubled:
            hold(k, "duplicate_key")
            continue
        if a is None or b is None:
            hold(k, "only_in_e1" if b is None else "only_in_e2")
            continue
        why = []
        for col in ("name", "quote", *columns):
            if not (a.get(col) or "").strip() and col in ("name", "quote"):
                why.append(f"{col}_empty")
            elif norm(a.get(col)) != norm(b.get(col)):
                why.append(f"{col}_disagrees")
        if a["doc_sha256"].strip().lower() != b["doc_sha256"].strip().lower():
            why.append("doc_sha256_disagrees")
        ctype = m["type"] if "type" in m else (a.get(m["type_column"]) or "").strip()
        if not why and (fmt.kind_of_type(ctype) not in LIST_KINDS or ctype != ctype.lower()):
            why.append("type_not_a_list_kind")  # written exactly as format.yaml spells it, or held
        if why:
            hold(k, ";".join(why), "" if why != ["type_not_a_list_kind"] else ctype)
            continue
        region = list_region if rule == "list" else a.get(m["region_column"])
        row = {"inst_id": prefix + k, "type": ctype, "name": a.get("name"), "region": region,
               "city": a.get(m["city_column"]) if m.get("city_column") else None,
               "source_url": url, "source_quote": a.get("quote"), "read_method": read_method,
               "retrieved": retrieved, "claude_status": "found",
               "checker1_result": "correct", "checker1_name": n1, "checker1_date": d1,
               "checker2_approved": "yes", "checker2_name": n2, "checker2_date": d2,
               "checker_note": f"E1 doc sha256 {a['doc_sha256'].strip()}; E2 doc sha256 {b['doc_sha256'].strip()}"}
        written.append(row)
        types[ctype] += 1
    for h in held:
        reasons[h["reason"]] += 1

    write_workbook(out, {"Institutions": written}, fmt)
    import openpyxl

    wb = openpyxl.load_workbook(out)
    ws = wb.create_sheet(PROVENANCE_SHEET)
    for r in (["role", "file", "sha256"],
              ["lists", list_file.name, file_sha256(list_file)],
              ["list", entry.entity_id, None],
              ["list_institution_type", entry.institution_type, None],
              ["e1", e1.name, file_sha256(e1)],
              ["e2", e2.name, file_sha256(e2)],
              ["e1_method", m1, None],
              ["e2_method", m2, None],
              ["mapping", mapping_path.name, file_sha256(mapping_path)],
              [f"checker1 ({n1}, {d1})", None, None],
              [f"checker2 ({n2}, {d2})", None, None],
              *([[f"type_count ({t})", n, None] for t, n in sorted(types.items())] if "type_column" in m else []),
              *([["count_mismatch_allowed", override, None]] if override else []),
              *([["identical_extractions", identical, None]] if identical else []),
              ["command", command, None]):
        ws.append([safe_cell(c) for c in r])
    wb.save(out)
    with held_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HELD_COLUMNS)
        w.writeheader()
        for h in held:
            w.writerow({c: safe_cell(h.get(c)) for c in HELD_COLUMNS})
    return {"written": len(written), "held": len(held), "reasons": dict(reasons), "held_path": held_path,
            "count_mismatch_allowed": override, "identical_extractions": identical, "types": dict(types)}


def main(argv: list[str] | None = None, out=print) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="scripts.os_list_sheet", description=__doc__.splitlines()[0])
    p.add_argument("--lists", required=True, metavar="DIR")
    p.add_argument("--list", required=True, dest="list_id", metavar="LIST_ID")
    p.add_argument("--country", required=True, help="the key of regions.yaml the list files are read with")
    p.add_argument("--e1", required=True)
    p.add_argument("--e2", required=True)
    p.add_argument("--e1-method", required=True, help="how E1 was extracted (recorded in Derived from)")
    p.add_argument("--e2-method", required=True, help="how E2 was extracted; must differ from E1's")
    p.add_argument("--mapping", required=True)
    p.add_argument("--checker1", required=True, nargs=2, metavar=("REF", "DATE"))
    p.add_argument("--checker2", required=True, nargs=2, metavar=("REF", "DATE"))
    p.add_argument("--out", required=True)
    p.add_argument("--allow-count-mismatch", action="store_true",
                   help="write the rows although a count differs (only when the list's count is not confirmed)")
    p.add_argument("--identical-extractions", metavar="REASON", default=None,
                   help="accept E1 and E2 with the same sha256, for the recorded reason")
    p.add_argument("--force", action="store_true", help="overwrite existing outputs")
    args = p.parse_args(argv)
    try:
        rep = build(lists=Path(args.lists), list_id=args.list_id, country=args.country, e1=Path(args.e1),
                    e2=Path(args.e2), mapping_path=Path(args.mapping), checker1=tuple(args.checker1),
                    checker2=tuple(args.checker2), out=Path(args.out),
                    allow_count_mismatch=args.allow_count_mismatch, e1_method=args.e1_method,
                    e2_method=args.e2_method, identical_reason=args.identical_extractions, force=args.force,
                    command="python -m scripts.os_list_sheet " + shlex.join(argv))
    except (Refused, OfficialListError, OSError) as e:  # each message names the file, line, list or mapping key
        out(f"refused: {e}")
        return 2
    out(f"wrote {args.out}: {rep['written']} rows; held {rep['held']} in {rep['held_path']}")
    if rep["count_mismatch_allowed"]:
        out(f"count mismatch allowed: {rep['count_mismatch_allowed']}")
    if rep["identical_extractions"]:
        out(f"identical extractions accepted: {rep['identical_extractions']}")
    for t, n in sorted(rep["types"].items()):
        out(f"type {t}: {n}")
    for why, n in sorted(rep["reasons"].items()):
        out(f"held ({why}): {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
