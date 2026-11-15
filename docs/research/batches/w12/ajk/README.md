# W12 HED AJK public colleges: list workbooks (2026-11-15, LOCAL)

These are the four HED AJ&K lists in docs/research/lists/ajk.yaml, 177 lines in total:
- `ajk-hed-postgraduate-colleges`: 14 lines, https://hed.ajk.gov.pk/post-graduate-colleges/;
- `ajk-hed-degree-colleges`: 75 lines, https://hed.ajk.gov.pk/degree-colleges/;
- `ajk-hed-model-science-colleges`: 7 lines, https://hed.ajk.gov.pk/model-science-colleges/;
- `ajk-hed-inter-colleges`: 81 lines, https://hed.ajk.gov.pk/inter-colleges/.

They are loaded as list workbooks `docs/research/batches/PAI-Research-W12-ajk-hed-<list>-colleges.xlsx`, built with
`backend/scripts/os_list_sheet.py` (P2-T29) from two independent extractions. id_prefixes `AJ-HEDCOL-PG-`,
`AJ-HEDCOL-DEG-`, `AJ-HEDCOL-MSC-`, `AJ-HEDCOL-INT-` (no existing id uses them), type public_college, region `list`.

## The two extractions
Each extraction was made by a different agent, from its own curl download on 2026-11-15 at about 00:44 UTC.
`source-extractions/E1/` and `source-extractions/E2/` hold each agent's files unchanged: the four CSVs, the raw pages
(`raw/`), the script, the download log, the check report and `notes.md`.

| | Method label | How |
|---|---|---|
| E1 | python stdlib html.parser tr walk | `HTMLParser` subclass walks every `<tr>`; a data row has exactly 2 cells, the first all digits, no hidden ancestor |
| E2 | lxml XPath table cells | `//main//table[not(@id='wpfront-notification-bar-table')]//tr[td]`, exactly 2 `td`, `text_content()` |

Both found every list's row_count (14, 75, 7, 81) with serials 1..N, and agree on key, name and quote for 177/177 rows.
quote = `"<serial> | <name>"`; city and page are empty. Both agents checked the pages for injected content (the parent
site ajk.gov.pk is compromised) and found none: the only off-site links are the WordPress `gmpg.org` profile link and a
Google Maps embed; the WPFront notification bar ("The tests and interviews have been
postponed due to a court stay order.") is visible and on-topic. Its spacer and reopen-button divs and the "Skip to
content" link are hidden. Neither extraction reads the bar as a row.

### Raw page sha256s
| list | E1 raw sha256 | E2 raw sha256 | normalised sha256 (both) |
|---|---|---|---|
| postgraduate | dfd2d4888d5787438d49c4e0b28c228144dea2bfba610801e311a4e7ef4cf7e3 | 9ebdfa8a3f94763d2251b2e97c6fc72583ff43f9102b20b8447ac5b786e71adc | 33c77aed3f463355af63926f0fba037b30b7439510b2eef9c2b9b6fb82648985 |
| degree | 2fa516b94a7d9855b2e4a255ceeaccc6c99fe85baa6395818a843ccfc07e3145 | 56238b085c549935c6dea4d2a9deccebf2e1410cae3480bc6cab86fba81d3693 | 666e424399f21f6513b8a91c275774f4b880c4b85d4dcd70d6dda50e09fea85d |
| model science | b40960ecd75f00c58c48e71abe454fc7ca924c7002685f2b256ae559a60494e2 | 11a79bf04809940a0acf6b45e433206e3ae8b6ff6bbd0a9482bdbdaafeb56819 | ada8065a9c80ce3604228a715a938eff2a1bb51bc88f3cfe6a51074bc88e3dea |
| inter | 838de00de46aca977c34edd6c63fc83084dae0934120edfa76796509322dea61 | 481cd26730613f1805f0c2aea799fb1e3528f1594a8bbb9aba5f61a635aac12d | e84622bbccb7bd555292771bf44abeccb8d6a5c2ef54ca47a08005570e15b958 |

## Why the inputs in `E1/` and `E2/` are derived (controller ruling, for the owner to confirm)
The two downloads of each page differ only in Cloudflare's per-request email-protection attribute in the footer,
`data-cfemail="<hex>"` (one per page), so the raw sha256s differ although the documents are the same.

Rule: **the document identity is the sha256 of the raw page with every `data-cfemail="<hex>"` value replaced by
`data-cfemail=""`.**

`derive.py` (run as `docker run --rm pai-ci-py python -I /w/derive.py /w`) does this for both extractions alike, each from
its own raw file:
- it stops unless every row's doc_sha256 is the sha256 of that extraction's own raw page;
- it sets doc_sha256 to the normalised sha256 of that raw page (1 attribute blanked per page);
- nothing else is changed. It checks that each source CSV re-serialises to its exact bytes (CRLF, minimal quoting)
  before it writes.

The normalised sha256 is the same for E1 and E2 on all four pages, so the blanked pages are byte-identical.

## Build
`build.sh` (run from `backend/`, in `docker run --rm pai-ci-py`) uses the mappings in `mappings/` (read_method
"curl + HTML text strip", retrieved 2026-11-15) and checkers `claude-w12-ajk-e1` / `claude-w12-ajk-e2`, both dated
2026-11-15.

### Identical CSV bytes: controller ruling (for the owner to confirm)
The agents' CSVs differ only in the doc_sha256 column. Once that column holds the normalised sha256, the derived E1 and
E2 CSVs are byte-identical for all four lists:
- postgraduate ac22365038077ed1cd8dd32763167e2c80f311621f555e6142982928705921bd;
- degree 9e1151b3904d92642b48f93e6d30aed28136df97d76402770538b751e67dcf75;
- model science 56765349a87e6d6258e6141e6461ba74acd797662dfb22162aaf780a66b8dfd6;
- inter cbb914636c3da747314a56703714a40b4bfc0418f5d42bff1d83d3033f1fe43f.

Without `--identical-extractions` the tool refuses them (a first run did, exit 2, nothing written). The controller
allowed it with this reason, which is in `build.sh` and in each workbook's "Derived from" sheet:

> Two independent curl downloads, parsed by two different parsers (python stdlib html.parser tr walk; lxml XPath table cells) to the same output spec; the raw pages differ only in Cloudflare's per-request data-cfemail footer value, and with it blanked they are identical (normalised doc_sha256); the identical derived CSV bytes are agreement, not a copy (controller ruling 2026-11-15, for the owner to confirm)

Result: 14, 75, 7 and 81 rows written (177), all public_college, 0 held (the `.held.csv` files have only the header).

## Dry run (validate, 2026-11-15)
`validate <workbook> --country PK --lists ../docs/research/lists --allow-list app/os/knowledge/sources/lists`, from
`backend/` in `docker run --rm pai-ci-py`:

| list | accepted | unconfirmed | queued | rejected | skipped |
|---|---|---|---|---|---|
| postgraduate | 0 | 14 | 0 | 0 | 0 |
| degree | 0 | 75 | 0 | 0 | 0 |
| model science | 0 | 7 | 0 | 0 | 0 |
| inter | 0 | 81 | 0 | 0 | 0 |

Every row's reason in the report is `check_unclear_or_missing` ("checker 1 is not a check the owner accepted; checker 2
is not a check the owner accepted"): validate runs in owner-accepted mode, which does not know the W12 checker refs
(FU-12). The report gives one reason per row, so `source_not_on_allow_list` is not shown here.

## Allow-list
hed.ajk.gov.pk is not on the allow-list (`app/os/knowledge/sources/lists`), because its parent site ajk.gov.pk carries
spam (W13 checks, D-ALLOW). Once the checker refs are registered and attested, these rows load `unconfirmed` (`source_not_on_allow_list`), but they count for
gate 6.

## Overlap with batches 1-5 and the other W12 workbooks
`overlap_check.py` (run in `docker run --rm pai-ci-py`, output in `overlap-check.txt`) compares every AJK name with the
Institutions rows of batches 1-5 v4 and the 12 other W12 workbooks (1898 rows):
- 0 exact matches of the normalised name;
- 18 rows where all of the AJK name's place words appear in the target name. They are all other places with the same
  word: Kotli Sattian (Rawalpindi), Muzaffarabad (Multan; Landhi, Karachi), Shad Bagh (Lahore), Nabi Bagh (Karachi);
- no HED college row in those files has the AJK region. The AJK rows there are universities, boards, the JAC, the HED
  admission body and 3 PMDC medical colleges (PK-PMDC-1, -123, -124), and none of them is one of these colleges.

No candidate for an alias.

## Before the import
- Register the reviewer refs `claude-w12-ajk-e1` and `claude-w12-ajk-e2` (`backend/scripts/os_reviewers.py`). Each must
  attest each workbook's batch ref.
- The xlsx bytes are not reproducible (zip timestamps).
