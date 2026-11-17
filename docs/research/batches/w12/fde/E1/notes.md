# D-FDE E1 notes: fde-hssc-participating-colleges

## Method
- Download: curl (`-A "Mozilla/5.0"`, `-D` headers saved), no paid tools. Raw bytes and headers are in `raw/`, and the log is in `raw/downloads.txt`.
- Extract: stdlib `html.parser`, in `scripts/extract_htmlparser.py`. It ran as `docker run --rm pai-ci-py python -I ...` with raw/ and scripts/ mounted read-only.
- Rows: each `<tr>` inside `<tbody>` of `table.c-table`, with 5 cells: S# | Code | College | Phone | Location.
  - key = S# cell text.
  - name = the text inside `<strong>` in the College cell.
  - address = the text of `span.u-muted` in the College cell, when present.
  - Whitespace is collapsed and stripped. HTML entities are decoded (convert_charrefs).
- quote = "<key> | <name>", plus " | <address>" when the table prints the muted address line. This holds for 52 of 82 rows.
- city = empty. The table has no city column. page = empty.

## URLs downloaded (all HTTP 200, 2026-11-15 UTC)
| file | URL | time (UTC) | sha256 | bytes |
|---|---|---|---|---|
| per200_a.html (**source of the CSV**) | https://eadmissions.fde.gov.pk/hssc/institutes.php?per=200&page=1 | 01:21:19Z | 20331e1e0dfd9e17e48b68224d0318f5626ee1186a652b7e2c0d243b6e418f81 | 59456 |
| per200_b.html (repeat) | same | 01:21:19Z | 20331e1e...8f81 (identical) | 59456 |
| noext_per200.html | https://eadmissions.fde.gov.pk/hssc/institutes?per=200&page=1 | 01:21:21Z | 20331e1e...8f81 (identical) | 59456 |
| default.html | https://eadmissions.fde.gov.pk/hssc/institutes | 01:21:18Z | cb1a23057a16e585c6c3abe8323db86ba82f53dfb70b6849d131ebeb1903be5d | 39955 |
| default_p2.html | https://eadmissions.fde.gov.pk/hssc/institutes?page=2 | 01:21:20Z | 3236a0c34561393557d98309a56b37e29f00d2f188303417a2823c62de294a45 | 27096 |

## Pagination findings
- The stored URL `/hssc/institutes` returns 200 with the same bytes as `/hssc/institutes.php`. Its default view shows 50 rows: "Showing 1–50 of 82".
- `?page=2` shows "Showing 51–82 of 82" (32 rows).
- `?per=200&page=1` shows "Showing 1–82 of 82", so every row is on one page. The pager offers per = 25/50/100/200.
- Cross-check: I extracted default.html and default_p2.html with the same script into `crosscheck/crosscheck_paged.csv`. Its key, name and quote columns are identical to the main CSV. Only doc_sha256 differs, as expected.

## Per-request tokens
- The two per=200 downloads have byte-identical bodies, so there is no csrf token or nonce in the HTML.
- Only these response headers differ: `Date`, `Set-Cookie: fde_sess=...` (a session id), the Cloudflare `Report-To` (NEL `s=` signature) and `CF-RAY`.
- The asset `?v=` query strings are the same in both downloads.

## Checks
- 82 rows. Keys are 1..82, unique and contiguous, and page order equals key order.
- No empty names and no duplicate names.
- Hidden or injected content: there are no elements with `hidden`, `display:none`, `visibility:hidden` or `aria-hidden=true`, and no iframe or inline script. The only script is /hssc/assets/js/main.js.
  - There is one HTML comment, in the nav: `<a class="c-masthead__staff" href="/hssc/login">Staff sign in</a>`. It is not table content.
- The ledger line for S# 78 matches: "ISLAMABAD MODEL COLLEGE FOR GIRLS (POSTGRADUATE)F-7/2,ISLAMABAD", code IMCGPG-F7/2, phone 0519102528.
- Main CSV sha256: ee306f69545b4078f394c552047385cd609a53978ee1e8cf42751e345004ae3c

## Odd rows (kept verbatim)
- 30 rows have no address line: 3, 7, 8, 12, 14, 15, 16, 18, 26, 28, 30, 31, 37, 38, 43, 47, 52, 53, 54, 61, 62, 63, 64, 66, 67, 68, 71, 73, 74 and 82.
- The address equals the name in rows 2, 34, 42 and 59, so the name appears twice in their quote.
- Name spacing is as printed, e.g. row 78 "(POSTGRADUATE)F-7/2,ISLAMABAD" and row 79 "( Post-Graduate Margalla)".
- Some website links are junk: `https://Nil`, `https://NIL`, `https://-`, `https://Facebook page`, `https://fb user ID imcgbharakahu01` and `https://impcch84`. Links are not part of the CSV.
- The Location cell holds either a Google Maps link ("Map") or "—". It is not used.
