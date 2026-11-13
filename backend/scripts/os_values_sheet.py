"""Build a batch file in the one research format from re-entered values and their checks (P2 spec §4.6, §11.3; R-67,
R-68). Nothing is computed or parsed: each cell is copied from the base file, the values CSV or a check CSV.

    python -m scripts.os_values_sheet BASE.xlsx --mapping MAP.yaml --values VALUES.csv \\
        [--check CHECK.csv --checker-name NAME --checker-date DATE]... --out OUT.xlsx

The mapping (data) names the base sheet and its key column, which values CSV column goes to which canonical column,
and, for each --check CSV in the same order, which checker it is (1 or 2), its column mapping and an optional
`translate` of its result words and `skip_results` (result words that hold the row back for review: it is not
written). For each key of the values CSV the base row is read the way the import reads it
(legacy layouts converted), its checker columns are cleared, and the value and checker columns are set from the CSVs.
A key not in the base sheet, a key twice in one check file and a values row with none of its mapped value columns
filled are reported and not written. A check result outside the format's vocabulary is written
as empty, so the import treats the row as not checked by that checker. The output holds the changed sheet, empty
other sheets, the Lists sheet and a "Derived from" sheet (file names, sha256, the command). The inputs are not changed.
Exit code 2 when refused.
"""

import argparse
import csv
import shlex
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import yaml

from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.reader import SheetError, file_sha256, read_batch
from app.os.knowledge.sheets.template import write_workbook

PROVENANCE_SHEET = "Derived from"


def _csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        r = csv.DictReader(fh)
        return list(r.fieldnames or []), list(r)


def _cell(v: str | None) -> str | None:
    return (v or "").strip() or None


def build(base: Path, mapping_path: Path, values: Path, checks: list[tuple[Path, str, str]], out: Path,
          command: str) -> dict:
    """Write the derived workbook; return the report (counts and the problems by key)."""
    fmt = load_format()
    mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    sheet, key = mapping["sheet"], mapping["key"]
    if sheet not in fmt.sheets or fmt.sheets[sheet].key != key:
        raise ValueError(f"mapping: {sheet}/{key} is not a sheet and key of the format")
    canonical = fmt.all_columns(sheet)
    specs = mapping.get("checks") or []
    if len(specs) != len(checks):
        raise ValueError(f"mapping has {len(specs)} check(s), {len(checks)} --check file(s) given")
    inputs = [base, mapping_path, values, *(c[0] for c in checks)]
    if out.resolve() in {p.resolve() for p in inputs}:
        raise ValueError("the output must be a new file, not an input")

    header, vrows = _csv(values)
    if key not in header:
        raise ValueError(f"{values.name}: no key column {key}")
    for src, dst in mapping["values"].items():
        if src not in header or dst not in canonical or dst in fmt.checker_columns:
            raise ValueError(f"values mapping {src} -> {dst}: not a CSV column or not a value column of {sheet}")
    # the columns that make a fact (format data); a values row with none of its mapped ones filled is not written
    fact_cols = set(fmt.raw["programme_facts"]) if sheet == "Programmes" else {"value"} if sheet == "Facts" else set()
    mapped_values = [src for src, dst in mapping["values"].items() if dst in fact_cols]
    numbers = [spec.get("checker") for spec in specs]
    if any(n not in (1, 2) for n in numbers) or len(set(numbers)) != len(numbers):
        raise ValueError(f"mapping: each check needs a distinct `checker` of 1 or 2, got {numbers}")

    problems: list[tuple[str, str]] = []
    check_rows = []
    for (path, name, date), spec in zip(checks, specs):
        n = spec["checker"]
        result_col = {1: "checker1_result", 2: "checker2_approved"}[n]
        allowed = set(fmt.check1_results) if n == 1 else set(fmt.check2_values)
        cheader, crows = _csv(path)
        cols = spec["columns"]
        if key not in cheader or any(c not in cheader for c in cols) or result_col not in cols.values():
            raise ValueError(f"{path.name}: needs {key} and columns {list(cols)}, one of them mapped to {result_col}")
        if any(dst not in ("checker_note", result_col) for dst in cols.values()):
            raise ValueError(f"{path.name}: checker {n} maps only to {result_col} and checker_note")
        translate = {str(a).strip().lower(): str(b).strip() for a, b in (spec.get("translate") or {}).items()}
        skip = {str(x).strip().lower() for x in spec.get("skip_results") or ()}
        by: dict[str, dict] = {}
        doubled: set[str] = set()
        for line, r in enumerate(crows, start=2):
            k = _cell(r.get(key))
            if k is None:
                problems.append((f"{path.name} line {line}", f"checker{n}_no_key"))
            elif k in by:
                doubled.add(k)
            else:
                by[k] = r
        result_src = next(src for src, dst in cols.items() if dst == result_col)
        check_rows.append(SimpleNamespace(n=n, result_col=result_col, result_src=result_src, allowed=allowed,
                                          cols=cols, translate=translate, skip=skip, name=name, date=date, by=by,
                                          doubled=doubled))

    batch = read_batch(base, fmt)
    by_key: dict[str, list[dict]] = {}
    for r in batch.sheets[sheet]:
        by_key.setdefault(str(r.get(key)), []).append(r)

    counts: Counter = Counter(written_without_value=0)
    written, seen = [], set()
    for v in vrows:
        k = _cell(v.get(key))
        if k is None or k in seen:
            problems.append((str(k), "duplicate_key" if k else "no_key"))
            continue
        seen.add(k)
        base_rows = by_key.get(k, [])
        if len(base_rows) != 1:
            problems.append((k, "not_in_base" if not base_rows else "several_base_rows"))
            continue
        doubled_in = [ch.n for ch in check_rows if k in ch.doubled]
        if doubled_in:  # two answers from one check: neither is used, the row waits
            problems.append((k, f"checker{doubled_in[0]}_duplicate_key"))
            continue
        if mapped_values and not any(_cell(v.get(src)) for src in mapped_values):
            problems.append((k, "no_value_not_written"))
            continue
        # a check that doubted the value holds the row back for review: it is not loaded on the other check alone
        if any(k in ch.by and (_cell(ch.by[k].get(ch.result_src)) or "").lower() in ch.skip for ch in check_rows):
            problems.append((k, "held_for_review"))
            continue
        row = {c: base_rows[0].get(c) for c in canonical}
        for c in fmt.checker_columns:  # the base checks were of the base row, not of these values
            row[c] = None
        for src, dst in mapping["values"].items():
            row[dst] = _cell(v.get(src))
        notes = []
        for ch in check_rows:
            n, c = ch.n, ch.by.get(k)
            if c is None:
                counts[f"checker{n}_missing"] += 1
                continue
            for src, dst in ch.cols.items():
                text = _cell(c.get(src))
                if dst == "checker_note":
                    if text:
                        notes.append(f"C{n}: {text}")
                    continue
                if text is not None:
                    text = ch.translate.get(text.lower(), text)
                if text is None or text.lower() not in ch.allowed:
                    if text is not None:
                        counts[f"checker{n}_outside_vocabulary"] += 1
                    counts[f"checker{n}_empty"] += 1
                    continue
                row[ch.result_col], row[f"checker{n}_name"], row[f"checker{n}_date"] = text, ch.name, ch.date
                counts[f"checker{n}_{text.lower()}"] += 1
        row["checker_note"] = " | ".join(notes) or None
        if not any(_cell(str(row[c])) for c in fact_cols if row.get(c) is not None):
            counts["written_without_value"] += 1
        written.append(row)
    for ch in check_rows:
        counts[f"checker{ch.n}_keys_not_in_values"] = len(set(ch.by) - seen)
        problems += [(k, f"checker{ch.n}_duplicate_key") for k in sorted(ch.doubled - seen)]
    counts["written"], counts["not_written"] = len(written), len(problems)

    write_workbook(out, {sheet: written}, fmt)
    import openpyxl

    wb = openpyxl.load_workbook(out)
    ws = wb.create_sheet(PROVENANCE_SHEET)
    ws.append(["role", "file", "sha256"])
    ws.append(["base", base.name, batch.sha256])
    ws.append(["values", values.name, file_sha256(values)])
    for (path, name, date), ch in zip(checks, check_rows):
        ws.append([f"checker{ch.n} ({name}, {date})", path.name, file_sha256(path)])
    ws.append(["mapping", mapping_path.name, file_sha256(mapping_path)])
    ws.append(["command", command, None])
    wb.save(out)
    return {"counts": dict(counts), "problems": problems}


def main(argv: list[str] | None = None, out=print) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = argparse.ArgumentParser(prog="scripts.os_values_sheet", description=__doc__.splitlines()[0])
    p.add_argument("base")
    p.add_argument("--mapping", required=True)
    p.add_argument("--values", required=True)
    p.add_argument("--check", action="append", default=[])
    p.add_argument("--checker-name", action="append", default=[])
    p.add_argument("--checker-date", action="append", default=[])
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        if not len(args.check) == len(args.checker_name) == len(args.checker_date):
            raise ValueError("give one --checker-name and one --checker-date per --check")
        rep = build(Path(args.base), Path(args.mapping), Path(args.values),
                    [(Path(c), n, d) for c, n, d in zip(args.check, args.checker_name, args.checker_date)],
                    Path(args.out), "python -m scripts.os_values_sheet " + shlex.join(argv))
    except (ValueError, SheetError, KeyError, TypeError, OSError, yaml.YAMLError) as e:
        out(f"refused: {e}")
        return 2
    out(f"wrote {args.out}")
    out(", ".join(f"{k} {v}" for k, v in sorted(rep["counts"].items())))
    grouped: dict[str, list[str]] = {}
    for k, why in rep["problems"]:
        grouped.setdefault(why, []).append(k)
    for why, keys in grouped.items():
        out(f"not written ({why}, {len(keys)}): {', '.join(keys)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
