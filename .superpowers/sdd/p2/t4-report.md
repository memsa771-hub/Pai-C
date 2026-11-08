# P2-T4 report: reading (R-74, R-29, R-72)

Branch `pc/p2-t4-reading`, cut from T3 (e0814db). Migration `os_0027_reading` chains on T3's `os_0026` (not `os_0025`, because this branch is cut from T3). T3's later fixes have NOT been merged yet; the coordinator will say when.

## Environment: what is installed
- Installed and used: Pillow 12.3 (with raqm shaping), reportlab, pypdf, pypdfium2, Playwright 1.64 with Chromium 1243 under `/opt/pw-browsers` (Playwright expects 1248, so tests launch it by path through `OS_RENDER_BROWSER` / a glob; `/usr/bin/google-chrome` also works). Fonts: FreeSerif covers Urdu (DejaVu does not: no ے ہ ۔).
- NOT installed: `tesseract` binary, `pytesseract`, `docling`. Nothing was installed or downloaded.

## Bake-off: what could really be compared
Nothing real. No OCR engine exists here, so `python scripts/scan_bakeoff.py` prints "tesseract not run, docling not run, winner none". What was proven: the harness (5 fictional cases built in memory: English PNG, English scan PDF, blurred English PNG, Urdu PNG, Urdu scan PDF) scores fake engines correctly (quote match by `quote_on_page`, similarity, time, failure counts, winner rule "every quote matches, no failure") and reports uninstalled engines as `not run`. The real-engine tests (`test_real_tesseract_*`, `test_real_docling_*`, `test_installed_engines_*`) skip here. The P2-D13 bake-off decision is therefore still open: someone must run the script where Tesseract and Docling are installed. No paid vision adapter was built (cost cap).

## Built
- `normalise.yaml` + `text.normalise`: folds Arabic yeh / alef maksura, kaf, heh to the Urdu forms, removes diacritics, tatweel, ZWNJ/ZWJ, maps Arabic-Indic and Extended digits to ASCII. Letters that make different words (bari yeh, aspirate heh) are not folded. Output is identical to the old function for text already in NFC form (normal Latin text), tested; decomposed text is now composed. `detect_language`: language set only for scripts the data maps (Arabic script to `ur`); Latin gets none, so existing flows are unchanged.
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

## OCR bake-off with Tesseract (added 2026-11-07, after Tesseract 5.3.4 with eng, osd, urd was installed)

Run: `python scripts/scan_bakeoff.py` in `backend/` (5 fictional cases built in memory), three times. The real-binary Tesseract
test (`test_real_tesseract_reads_an_english_scan`) and the installed-engines bake-off test ran and passed (not skipped); the
only skipped scan test is Docling's. Accuracy was identical in all three runs; time was not (see the load note).

| Case | Quotes matched | Similarity | Time, quiet run (s) |
|---|---|---|---|
| English PNG | 2/2 | 0.88 | 0.4 |
| English scan PDF | 2/2 | 0.88 | 2.7 |
| English blurred PNG | 1/2 | 0.985 | 5.0 |
| Urdu PNG | 0/2 | 0.95 | 2.9 |
| Urdu scan PDF | 0/2 | 0.81 | 1.5 |
| Total | 5/10 (50%) | mean 0.90 | mean 2.5, 0 failures |

(English similarity of 0.88 is low only because the title line "Admissions notice" is not in the quote set, so it counts against
the ratio; the two quoted lines were read exactly.)

What the misses were (output inspected):
- **English blurred (Gaussian blur radius 2.5):** the digit "1" was read as "|" ("close on | August 2027."). The fee line matched.
- **Urdu PNG:** the text is almost all correct (similarity 0.95), but the quote match fails for two reasons.
  1. Tesseract wraps digit runs in invisible direction marks (U+200E, U+200F). `normalise` does not remove them. Stripping them
     (a data-only change to `normalise.yaml` `remove.singles`, which I did NOT make because code and data are frozen for the review)
     makes the first Urdu line match; I checked this in a scratch script.
  2. In the second line the number is read in the wrong order: "1000" came out as "0001". That is a real misread, the dangerous
     kind (a wrong amount), and it correctly fails the quote match.
- **Urdu scan PDF (rasterised at scale 2):** lower quality (similarity 0.81): several letters wrong ("اخری قارخ" for "آخری تاریخ") and the digits garbled.

Timing under load: the machine had a load average of about 12 (other suites running). In one run the two English cases hit our
60 s timeout (`ScanFailed`, 2 failures) and the other cases took 8 to 35 s; the run before and after took 0.4 to 9 s. Tesseract
multithreading under load is the likely cause (not verified); `OMP_THREAD_LIMIT=1` for the subprocess is the usual remedy and
should be tried in a code change.

**Docling was not compared.** It is not installed. Its adapter is unverified. The P2-D13 choice of engine is therefore between
Tesseract and nothing for now.

**Recommendation: Tesseract does NOT pass the bar on these fixtures.** The bar (spec P2-D13) is that the winner must pass the quote
match on the fixtures; it matched 5 of 10 quotes, and the failures include a wrong number read from a scan. What it does show:
- English clean scans: pass (including the scanned PDF), at ordinary speed.
- Urdu: usable only with a person comparing it. That is what the design already requires for every OCR fact: they stay `unconfirmed`
  (R-72), so Tesseract output may be used as a draft for checkers but must never make a `confirmed` fact. That rule is in the code.
- Before deciding, (1) add the direction marks U+200E, U+200F (and U+202A to U+202E, U+2066 to U+2069) to `normalise.yaml` and rerun,
  (2) set a thread limit and a longer per-page timeout, (3) try a higher rasterisation scale and `--psm` for the PDF case,
  (4) run Docling when it can be installed, (5) judge on real notices, not only these synthetic ones (clean synthetic fixtures
  are easier than real scans, so real results are likely worse). Until then, record OCR as "usable for English draft reading,
  not for Urdu numbers".

## Review fixes (2026-11-08)

Merged `origin/pc/p2-t3-sources` first (T3 review fixes, including `flags=` for atomic suspect flagging: the render and OCR
paths pass `flags` on to `_inspected`).

| # | Fix |
|---|---|
| 1 | WebRTC off: launch flags `--force-webrtc-ip-handling-policy=disable_non_proxied_udp` and `--webrtc-ip-handling-policy=disable_non_proxied_udp`, plus an init script that deletes `RTCPeerConnection`, `webkitRTCPeerConnection`, `RTCDataChannel`. Test: a page reads `typeof` of each (undefined) and `new RTCPeerConnection()` throws. |
| 2 | The browser runs in its own process (`render_child.py`, own session and process group, CPU, file-size and core-dump limits, empty environment, private working directory). When the worker is root the child drops to uid 65534 (`OS_RENDER_UID`), and Chromium KEEPS its sandbox here (it starts as that user without `--no-sandbox`; `OS_RENDER_NO_SANDBOX=1` is the operator's escape hatch). Flags `--js-flags=--max-old-space-size=<setting>`, `--disable-gpu`, `--disable-dev-shm-usage`, `--disable-extensions`. ONE wall-clock deadline (`render_timeout_s`, now 30) around the whole `render()`; at the deadline the process group is SIGKILLed. Playwright's Python `content()` has no timeout argument: the page default timeout is set (deadline minus 2 s) and the hard kill covers a hung `content()`. |
| 3 | Sub-requests: `render_max_requests` (60) and `render_max_bytes` (20 MB) in settings, enforced in the parent; allow-list, robots.txt and the host interval (sleeps, bounded by the time left) apply to every sub-request; streamed with a byte limit (`min(bytes left, page_max_bytes)`, declared and actual); redirects are not followed in the parent (the browser asks again, and the new URL is checked); none after the deadline. |
| 4 | R-72: a later successful read sets the source row `readable`; each field's open rows become `readable` once a fact exists for it, unless an unreadable page was marked for that field in the same run. |
| 5 | `open_fields` is computed from the facts actually stored (after the OCR cap), not from the verdicts. |
| 6 | `merge_read_info`: when one URL was read several ways, the strictest method is kept (human > ocr > render > fetch). |
| 7 | `rasterise_pdf(max_pixels=)` and image files: `ScanFailed` over `scan_max_pixels` (25 M), before anything is drawn. |
| 8 | `normalise`: NFC first; marks 0653-0655 are kept (they are parts of letters); ZWNJ/ZWJ removed only next to Arabic letters. U+200E and U+200F are removed (bake-off finding). |
| 9 | `detect_language`: a language code (`ur`) only with evidence (at least 3 Urdu-only letters, data in `normalise.yaml`); otherwise the script tag (`arab`); Latin and other scripts: none. Script tags (four letters) live on pages and snapshots (their constraint is now `^[a-z]{2,4}$`, migration `os_0027`); a FACT takes only a language code (`^[a-z]{2,3}$`), so a script tag is never copied to a fact. |
| 10 | Language tagging runs with the flags off, on purpose: P2-D14 makes it part of normalisation and reading, not of the render or OCR switches. It changes nothing for Latin pages (no label), and it adds no fact change unless the page's script is Arabic. NFC in `normalise` is the one other always-on change: text already in NFC (all normal Latin text) is unchanged; decomposed text is now composed. |
| bake-off | Tesseract now runs with `OMP_THREAD_LIMIT=1` and a 180 s per-page timeout (`scan_timeout_s`). |

### Bake-off re-run (Tesseract 5.3.4, same five fictional cases, three runs, identical numbers)

| Case | Quotes matched | Similarity | Time (s) |
|---|---|---|---|
| English PNG | 2/2 | 0.88 | 0.13 |
| English scan PDF | 2/2 | 0.88 | 0.34 |
| English blurred PNG | 1/2 | 0.985 | 0.15 |
| Urdu PNG | 1/2 (was 0/2) | 0.984 | 0.09 |
| Urdu scan PDF | 0/2 | 0.839 | 0.20 |
| Total | 6/10 (60%, was 50%) | mean 0.91 | mean 0.2 (was 2.5), 0 failures |

Docling still was not compared. Removing the direction marks fixed the first Urdu line. The thread limit cut the time per case by about 10x and the earlier 60 s timeouts did not recur (load average was 4 to 5). Still failing: the blurred "1" read as "|", the Urdu number "1000" read as "0001" (a real misread: correctly refused), and the Urdu scan PDF letters. The recommendation does not change: Tesseract does not pass the bar (6/10), and its Urdu output stays a draft for a person (OCR facts stay `unconfirmed`).

### Checks after the review fixes (merged with T3 at 3a8f13e)
tests/os: 2493 passed, 2 skipped (Docling is not installed), 1 xfailed. Legacy: 2560 passed, 13 skipped. tach ok, freeze clean, single OS head `os_0027`, traceability ok. The Tesseract tests ran and were not skipped.

## Review fixes, round 2 (2026-11-08)

| # | Fix |
|---|---|
| 1 | Launch flags `--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1`, `--disable-quic`, `--dns-prefetch-disable`; `WebTransport` is deleted by the init script. Test: a page opens a WebSocket and an image on the loopback address of the fixture server, adds a dns-prefetch link and fetches an off-list host; the render fetch answers only the allow-listed host; the fixture server never sees any of it, and `typeof WebTransport` is `undefined`. |
| 2 | Memory and processes. The child is put in a cgroup with `memory` and `pids` limits (`render_max_memory_mb` 1024, `render_max_pids` 256). **In this environment cgroup v1 is mounted and writable** (the memory and pids hierarchies); cgroup v2 is not present. The v1 path is tested (the child is in the group, the limit files hold the set values, the group is removed afterwards, stale empty groups of dead workers are swept). **The v2 path is written but has NOT been run anywhere.** Where no cgroup can be made, the unprivileged user gets `RLIMIT_NPROC` (tested) and **the memory limit is NOT enforced: only the JavaScript heap flag applies. That gap is known and open on such hosts.** `last_isolation` on the renderer says which a render had. |
| 3 | The gateway's per-host clock is shared: `PageGateway.pace(host, max_wait)` is used by the render sub-requests, and page fetches now also wait for a host that a render just asked (test). The stamp is in the worker process; other workers see only the `os_pages` rows (open). |
| 4 | `PR_SET_PDEATHSIG(SIGKILL)` is set in the child's preexec, after the user change (which would clear it), with a check that the worker is still alive. Test: a worker process is SIGKILLed while the browser waits; no browser process is left. |
| 5 | `close_field` runs only for fields whose stored fact is confirmed; an unconfirmed (for example OCR) fact keeps the field open for a checker (test). |
| 6 | "Latin byte-identical" is reworded to "identical for text already in NFC form" (report, plan, normalise.yaml, test name). |
| 7 | Hamza-yeh: U+06CC+U+0654, U+064A+U+0654 and U+0649+U+0654 all fold to U+0626 (`compose:` in `normalise.yaml`); a plain yeh stays different (test). |
