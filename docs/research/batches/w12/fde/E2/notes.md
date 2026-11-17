# D-FDE extraction E2: fde-hssc-participating-colleges

## Method
- Download: curl (`-sS -L`, desktop-browser User-Agent), raw bytes saved in `raw/`, response headers in `raw/*.headers`.
- Extract: lxml XPath (`scripts/extract_lxml.py`), run as
  `docker run --rm pai-ci-py python -I /s/extract_lxml.py ...`, with raw/ and scripts/ mounted read-only. Log: `scripts/run.log`.
- Rows: `//table[1]/tbody/tr`, 5 `td` each (S#, Code, College, Phone, Location).
  - `key` = the S# cell.
  - `name` = the `<strong>` text inside the College cell.
  - The address = `span.u-muted` inside the College cell, when present.
  - Only whitespace is collapsed. Nothing else is changed.
- `quote` = "<S#> | <name>", plus " | <address>" when the cell prints the `u-muted` address line (52 of 82 rows).
  Code, phone and map are not in the quote, per the brief.
- `city` is empty because the table has no city column. Many names and addresses contain "Islamabad", but no
  city field is printed.
- `page` is empty. `doc_sha256` is the sha256 of the per=200 page.

## Downloads (all HTTP 200, no redirects)
| file | URL | UTC | sha256 | bytes |
|---|---|---|---|---|
| raw/default.html | https://eadmissions.fde.gov.pk/hssc/institutes | 2026-11-15T01:21:14Z | cb1a23057a16e585c6c3abe8323db86ba82f53dfb70b6849d131ebeb1903be5d | 39955 |
| raw/per200_a.html | https://eadmissions.fde.gov.pk/hssc/institutes.php?per=200&page=1 | 2026-11-15T01:21:15Z | 20331e1e0dfd9e17e48b68224d0318f5626ee1186a652b7e2c0d243b6e418f81 | 59456 |
| raw/per200_b.html | https://eadmissions.fde.gov.pk/hssc/institutes.php?per=200&page=1 | 2026-11-15T01:21:15Z | 20331e1e0dfd9e17e48b68224d0318f5626ee1186a652b7e2c0d243b6e418f81 | 59456 |
| raw/default_p2.html | https://eadmissions.fde.gov.pk/hssc/institutes.php?page=2 | 2026-11-15T01:21:16Z | 3236a0c34561393557d98309a56b37e29f00d2f188303417a2823c62de294a45 | 27096 |

The CSV is built from raw/per200_a.html.

## Pagination
- `/hssc/institutes` (the stored URL) shows 50 rows per page by default: "Showing 1–50 of 82". It links to
  `/hssc/institutes.php?per=50&page=2`, and the per-page options are 25, 50, 100 and 200.
- `institutes.php?page=2` shows "Showing 51–82 of 82" (32 rows).
- `institutes.php?per=200&page=1` shows "Showing 1–82 of 82", all rows on one page.
- Cross-check: default page 1 + page 2 (50 + 32 rows) are identical, row for row (S#, name, address), to the
  per=200 page.

## Per-request tokens
- The two per=200 downloads are byte-identical (same sha256), so the HTML has no csrf, nonce or other
  per-request token.
- Only the response headers differ: the `Set-Cookie: fde_sess=...` value, `CF-RAY` and `Date`. Cloudflare served
  the page with no challenge.
- The asset `?v=` numbers are static cache-busters. They are the same in both downloads.

## Checks
- 82 rows. S# runs 1..82 in order, with no gaps and no duplicates.
- No empty names. Each College cell has exactly one `<strong>` and at most one address span.
- Hidden or injected content: none found.
  - There are no elements with `hidden`, `display:none`, `visibility:hidden` or `aria-hidden`.
  - There are no iframes and no inline `<style>`.
  - There is one external script, `/hssc/assets/js/main.js`.
  - There is one HTML comment, in the masthead nav (a commented-out "Staff sign in" link). It is outside the table.
  - The table body has 462 non-blank text nodes. That is exactly 82×5 cells + 52 address lines, so there is no
    extra text.
  - Only three classes are used in tbody: `c-table__mono`, `c-table__link` and `u-muted`.
- Result: no mismatch with the list's row_count of 82.

## Odd rows
- In rows 2, 34, 42 and 59, the address line repeats the name exactly. The quote still adds it, as the rule says.
- 50 rows have no website link; the name is plain `<strong>`. These are S# 5, 6, 11, 14-18, 20, 22, 24-32, 34, 37,
  38, 40, 41, 43, 49-53, 55-58, 60-68, 71-76 and 79.
- Row 1 links to `https://Nil`, a placeholder website on the source.
- Row 78 name: "ISLAMABAD MODEL COLLEGE FOR GIRLS (POSTGRADUATE)F-7/2,ISLAMABAD". It is printed with no space
  before "F-7/2" and matches the ledger line. Its address is "...F7 MARKAZ".
- Names mix upper and title case as printed. They are kept verbatim.
