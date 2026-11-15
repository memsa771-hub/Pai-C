# D-AJK extraction, E1 (stdlib html.parser)

## Download
curl -sS -L -A "Mozilla/5.0", one request per page, 2026-11-15 (UTC). Raw bytes in raw/, log in download-log.txt.

| list id | file | HTTP | UTC time | bytes | sha256 |
|---|---|---|---|---|---|
| ajk-hed-postgraduate-colleges | raw/post-graduate-colleges.html | 200 | 2026-11-15T00:44:41Z | 58173 | dfd2d4888d5787438d49c4e0b28c228144dea2bfba610801e311a4e7ef4cf7e3 |
| ajk-hed-degree-colleges | raw/degree-colleges.html | 200 | 2026-11-15T00:44:47Z | 65739 | 2fa516b94a7d9855b2e4a255ceeaccc6c99fe85baa6395818a843ccfc07e3145 |
| ajk-hed-model-science-colleges | raw/model-science-colleges.html | 200 | 2026-11-15T00:44:50Z | 56524 | b40960ecd75f00c58c48e71abe454fc7ca924c7002685f2b256ae559a60494e2 |
| ajk-hed-inter-colleges | raw/inter-colleges.html | 200 | 2026-11-15T00:44:52Z | 66533 | 838de00de46aca977c34edd6c63fc83084dae0934120edfa76796509322dea61 |

## Parse
scripts/extract.py, run as `docker run --rm pai-ci-py python -I /scripts/extract.py /raw /out` (raw/ and scripts/ mounted read-only).
A stdlib HTMLParser subclass walks every <tr>, collects <td>/<th> text (<br> = space), and tracks whether any open
ancestor is hidden (class "hidden", hidden attr, aria-hidden=true, or style display:none / visibility:hidden /
large negative offset / font-size:0 / opacity:0). A row is data only if it has exactly 2 cells, the first all digits,
and no hidden ancestor. Name = cell 2 with whitespace collapsed; quote = "<serial> | <name>". Per-row details in check.json.

## Checks
| list | rows | expected | serials 1..N | empty names | source table |
|---|---|---|---|---|---|
| postgraduate | 14 | 14 | yes | none | table 2 (the content table) |
| degree | 75 | 75 | yes | none | table 2 |
| model science | 7 | 7 | yes | none | table 2 |
| inter | 81 | 81 | yes | none | table 2 |

Skipped on every page: 1 row in table 1 (wpfront-notification-bar-table), one cell, text "The tests and interviews
have been postponed due to a court stay order." It sits inside `<div id="wpfront-notification-bar-spacer" class="...
hidden">`. It is a WordPress notice plugin, on-topic, not spam, and not a college row. Model-science page also has a
second, empty content table (`<table ... style="width: 308pt"></table>`), no rows.

## Injection check
No injected content found on any of the 4 pages.
- Link domains (href/src): only hed.ajk.gov.pk, gmpg.org (WordPress profile link) and maps.google.com (embed). No off-topic domains.
- No inline style with display:none, visibility:hidden, negative offsets, font-size:0, opacity:0 or clip.
  All inline styles are height/width only (table formatting).
- No spam keywords (replica, casino, slot, gacor, toto, poker, viagra, loan, bet, watch): 0 hits in each file.
- Only element hidden by class: the notification-bar spacer above (benign).
- No data row has a hidden ancestor.

## Odd rows (kept verbatim)
- degree 74: "GIRLS DEGREE COLLEGE, FATEHPUR Thakiala" (contains a comma; CSV-quoted).
- postgraduate 2: "post graduateCOLLEGE ABBASPUR for GIRLS" (missing space as printed).
- Mixed case as printed, e.g. degree 10 "BOYS DEGREE COLLEGE charhoi", 31 "ALI SOJaL", 73 "TrAR KHAL"; inter 75 "Sullot KOTHIAN".
- Possible duplicate places across names (not merged): degree 17 BOYS ... FATEHPUR THAKIALA vs 74 GIRLS ...; no exact duplicate names in any list.
- Model science 6: name cell ends with <br>; collapsed away.
