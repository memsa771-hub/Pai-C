# P2-T4 report: reading (R-74, R-29, R-72)

Branch `pc/p2-t4-reading`, cut from T3 (e0814db). Migration `os_0027_reading` chains on T3's `os_0026` (not `os_0025`, because this branch is cut from T3). T3's later fixes have NOT been merged yet; the coordinator will say when.

## Environment: what is installed
- Installed and used: Pillow 12.3 (with raqm shaping), reportlab, pypdf, pypdfium2, Playwright 1.64 with Chromium 1243 under `/opt/pw-browsers` (Playwright expects 1248, so tests launch it by path through `OS_RENDER_BROWSER` / a glob; `/usr/bin/google-chrome` also works). Fonts: FreeSerif covers Urdu (DejaVu does not: no ے ہ ۔).
- NOT installed: `tesseract` binary, `pytesseract`, `docling`. Nothing was installed or downloaded.

## Bake-off: what could really be compared
Nothing real. No OCR engine exists here, so `python scripts/scan_bakeoff.py` prints "tesseract not run, docling not run, winner none". What was proven: the harness (5 fictional cases built in memory: English PNG, English scan PDF, blurred English PNG, Urdu PNG, Urdu scan PDF) scores fake engines correctly (quote match by `quote_on_page`, similarity, time, failure counts, winner rule "every quote matches, no failure") and reports uninstalled engines as `not run`. The real-engine tests (`test_real_tesseract_*`, `test_real_docling_*`, `test_installed_engines_*`) skip here. The P2-D13 bake-off decision is therefore still open: someone must run the script where Tesseract and Docling are installed. No paid vision adapter was built (cost cap).

## Built
- `normalise.yaml` + `text.normalise`: folds Arabic yeh / alef maksura, kaf, heh to the Urdu forms, removes diacritics, tatweel, ZWNJ/ZWJ, maps Arabic-Indic and Extended digits to ASCII. Letters that make different words (bari yeh, aspirate heh) are not folded. Latin output is byte-identical (tested against the old function). `detect_language`: language set only for scripts the data maps (Arabic script to `ur`); Latin gets none, so existing flows are unchanged.
- `scan.py`: `ScanText` port, `ScanResult`, `ScanFailed`, `FixedScanText` (fake), `TesseractScanText` (CLI; tested against a fake executable and a skipped real-binary test), `DoclingScanText` (UNVERIFIED: written to Docling's documented API, tests skip), `rasterise_pdf` (pypdfium2), `scan_document`. Language codes in `scan_languages.yaml`.
- `render.py`: `PlaywrightRenderer`. The browser has no network: dead proxy, service workers blocked, and every GET is answered by the gateway's own httpx client only for URLs the allow-list accepts; other methods and URLs are aborted. `looks_like_js_shell` (thresholds in settings).
- `reading.py`, `readability.py`, `bakeoff.py`; gateway hooks in `pages.py` (3 small hooks, `renderer=` / `scanner=` optional). Failures become `not_readable:render` / `not_readable:ocr`, with a flagged snapshot and the original file kept when a source guard is set.
- `Page.read_method` / `Page.language`, persisted in `os_pages` so a cached OCR page is never mistaken for a fetched one.
- `NotReadableStore` (`os_not_readable`: one row for the source and one per open field; states open / collected / readable; `set_state` only closes open rows) for T5's `collect` item.
- `store_research`: a fact read by OCR is capped at `unconfirmed` (R-72); render/OCR read_method and language are recorded on the fact; not_readable pages are marked with the fields that still lack a confirmed fact (only when a store is passed).
- Worker: `OS_RENDER=1`, `OS_SCAN_ENGINE=tesseract|docling` (left out with a warning if not installed). Both off by default.
- Settings (additive): `render_shell_max_chars`, `render_timeout_s`, `render_browser_path`, `scan_min_pdf_chars`, `scan_max_pages`.

## Deviations
- Render uses request interception through the gateway client plus a dead proxy, not an in-process copy of `app/browser/egress.py` (Tach forbids importing it).
- `human` read_method and `collected` marking: T4 only defines the ceiling (`human` is never machine-confirmed) and the store; T5 builds the collect item and the human readings.
- `verified` from OCR/human readings stays T5's two-reviewer path.
- Migration number and parent as above; `os_pages` gains two columns (additive).
- Urdu fixture sentences are fictional and live only in tests; no student sentences added.

## Interfaces for others
- T5: `NotReadableStore.open_rows/set_state`, `machine_status_ceiling`, `SnapshotStore.original(id)` for the evidence view (original PDFs/images are kept for scans).
- T6: `scan_document`, `machine_status_ceiling`, `Page.read_method`.
- T3 merge: my hooks sit in `pages.py` `__init__`, `_store`/`_cached`, the three `_page` branches, and `worker.py` (gateway construction and register_research call). I call `gw._inspected(...)` and `guard.snapshots.save(...)` unchanged and annotate snapshots through my own `annotate_snapshot` (no change to `SnapshotStore.save` or `SourceGuard.inspect`).

## Counts and checks
- tests/os: 2444 passed, 4 skipped, 1 xfailed. New T4 tests: normalise 7+, scan 10 (2 skip), render 8, scan gateway 6, not_readable 7, bake-off 5 (1 skip).
- legacy: 2559 passed, 14 skipped. tach ok. freeze clean. alembic: single OS head `os_0027`. traceability ok. Ruff clean on new files.
