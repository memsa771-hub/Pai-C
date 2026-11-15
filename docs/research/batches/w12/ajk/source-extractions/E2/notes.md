# D-AJK extraction E2

## Download (curl -sS -L, UA "Mozilla/5.0"); log in download.log
| list id | file | HTTP | UTC | bytes | sha256 |
|---|---|---|---|---|---|
| ajk-hed-postgraduate-colleges | raw/post-graduate-colleges.html | 200 | 2026-11-15T00:44:42Z | 58173 | 9ebdfa8a3f94763d2251b2e97c6fc72583ff43f9102b20b8447ac5b786e71adc |
| ajk-hed-degree-colleges | raw/degree-colleges.html | 200 | 2026-11-15T00:44:47Z | 65739 | 56238b085c549935c6dea4d2a9deccebf2e1410cae3480bc6cab86fba81d3693 |
| ajk-hed-model-science-colleges | raw/model-science-colleges.html | 200 | 2026-11-15T00:44:50Z | 56524 | 11a79bf04809940a0acf6b45e433206e3ae8b6ff6bbd0a9482bdbdaafeb56819 |
| ajk-hed-inter-colleges | raw/inter-colleges.html | 200 | 2026-11-15T00:44:52Z | 66533 | 481cd26730613f1805f0c2aea799fb1e3528f1594a8bbb9aba5f61a635aac12d |

## Method
- Parser: lxml XPath (scripts/extract_e2.py), run as
  `docker run --rm -v <E2>:/w pai-ci-py python -I /w/scripts/extract_e2.py /w/raw /w`.
- Rows: `//main//table[not(@id='wpfront-notification-bar-table')]//tr[td]`; each row must have exactly 2 `td`
  (serial, name); text_content() with whitespace collapsed.
- Each row's ancestry is checked for hiding (display:none, visibility:hidden, opacity:0, negative offsets,
  font-size:0, zero height/width, clip, class "hidden", hidden attr, aria-hidden) and for links. None found.
- quote = "<serial> | <name>"; city and page empty; doc_sha256 = raw sha256.
- Full per-list result: extract_report.json.

## Checks
| list | rows | expected | serials 1..N | empty names |
|---|---|---|---|---|
| postgraduate | 14 | 14 | yes | 0 |
| degree | 75 | 75 | yes | 0 |
| model-science | 7 | 7 | yes | 0 |
| inter | 81 | 81 | yes | 0 |

## Injection check: none found on these four pages
- Off-site hrefs: only `<link rel="profile" href="https://gmpg.org/xfn/11">` (standard WordPress head) and a Google
  Maps embed iframe (maps.google.com, "district complex muzaffarabad") in the footer. All other 43 hrefs are
  hed.ajk.gov.pk. No off-site scripts (only Cloudflare /cdn-cgi email-decode).
- No spam keywords (replica, watch, casino, slot, toto, gacor, bet, poker, judi).
- No inline style with display:none / visibility:hidden / negative offset / font-size:0 anywhere.
- Elements with class "hidden" or aria-hidden are standard theme parts: WPFront notification bar spacer and open
  button, font-awesome icons, the Elementor dropdown nav. The notification bar table (id wpfront-notification-bar-table)
  holds only "The tests and interviews have been postponed due to a court stay order." and is excluded.
- model-science-colleges.html has an extra empty `<table>` after the data table (no rows).

## Odd rows (kept verbatim)
- postgraduate 2: "post graduateCOLLEGE ABBASPUR for GIRLS" (missing space in source).
- postgraduate 1: "POSTGRADUATE COLLEGE for Girls MUZAFFARABAD" (mixed spelling with others).
- degree 74: "GIRLS DEGREE COLLEGE, FATEHPUR Thakiala" (comma, CSV-quoted).
- degree 73: "GIRLS DEGREE COLLEGE TrAR KHAL"; 31 "ALI SOJaL"; 10 "BOYS DEGREE COLLEGE charhoi" (mixed case in source).
- model-science 6: source cell ends with `<br>`; collapsed away.
- No names with non-ASCII characters; no duplicate names within a list.
