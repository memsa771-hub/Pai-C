# Research batches 1–5 (v2)

The owner returned these five files on 2026-11-06 as the batches researched at the start of the connection plan (master spec §8.6, R-67 to R-69).

| File | Institutions | Programmes | Facts (high-stakes) |
|---|---|---|---|
| Batch 1, national | 354 | 0 | 65 (58) |
| Batch 2, Punjab | 79 | 96 | 79 (75) |
| Batch 3, Sindh | 72 | 146 | 46 (40) |
| Batch 4, KP, Balochistan, ICT, AJK, GB | 46 | 41 | 86 (78) |
| Batch 5, universities (bachelor's) | 19 | 13 | 60 (52) |

## What state the rows are in (checked 2026-11-06)

- Each file has a "Verification v2" sheet. It records Claude's own re-check of 2026-11-03, not a person's check.
- In every file, the person-checker columns are empty on every row: `checker1_result`, `checker1_name`, `checker2_approved`, `checker2_name` and the rest.
- Some facts were read by a model, from an image or from a search excerpt (WebFetch, image, search_excerpt). There are 109 such rows in all.

So, under R-68, the import loads these rows with Claude's status (`found`, `unconfirmed`, `conflict` and so on) as their trust level.

- No row becomes `verified` until checker 1 and checker 2 are filled in.
- Rows that a model read must be re-fetched, and their quote matched word for word, before they can become `confirmed`.
- Older column layouts (the batch 2 and 3 Programmes sheets) are mapped into the canonical layout by the import (R-67), not by hand.

The files are kept unchanged as the source record. The P2 import (R-68) reads them from here.

## v3 (returned by the owner on 2026-11-06)

The v3 files add an AI first check on every row. Its name is "Claude – check 1". Checker 2 is empty everywhere. That check reported many tool limits: its web-reading credits ran out, some pages were blocked, and some pages were JavaScript-rendered. These are its results:

| | correct | unclear | not_readable | wrong |
|---|---|---|---|---|
| Institutions (570) | 400 | 102 | 68 | 0 |
| Programmes (296) | 75 | 195 | 26 | 0 |
| Facts (336) | 92 | 199 | 44 | 1 |
| of which high-stakes facts (303) | 89 | 175 | 39 | 0 |

One programme row has no check result.

**Owner decision (chat, 2026-11-06).** The batches are verified by AI, and both developers have viewed them and are comfortable with them, so they are to be used. The import applies the decision this way:

- **Rows the check marked `correct`** are accepted. The record says `checked_by: "Claude – check 1"` and `accepted_by: owner, 2026-11-06`.
- **Rows marked `unclear` or `not_readable`** are loaded as `unconfirmed`. The student sees them labelled "not confirmed yet". The P2 re-fetch and quote match (R-68) promotes a row automatically when the official page still carries the exact quote.
- **The row marked `wrong`** goes to the review queue and is not used.

v3 is the version to import. v2 is kept as history.

## v4 (returned by the owner on 2026-11-07)

The v4 files fill both checker columns on every row. The names in the files are "Claude – check 1" and "Claude – check 2 (independent)", both dated 2026-11-07. So both checks are AI checks, not two people. `PAI-v4-rows-needing-review.csv` lists the 73 rows the checks did not settle.

**Owner decision (chat, 2026-11-07).** "They have been verified and the developers have reviewed it as well, so you can use them." This extends the v3 decision to check 2. The import applies it this way:

- **A row accepted by both checks** (check 1 `correct`, check 2 `yes`) is loaded as `verified`. The record keeps who checked it: `checker1: "Claude – check 1"`, `checker2: "Claude – check 2 (independent)"`, `accepted_by: owner, 2026-11-07`, plus a note that the developers reviewed it. The audit log never names a person who did not check the row.
- **A row check 1 marked `unclear` or `not_readable`, or with no result,** is loaded as `unconfirmed` and shown as "not confirmed yet". The R-68 re-fetch and quote match can promote it to `confirmed`.
- **A row check 1 marked `correct` but check 2 did not approve (`no`)** goes to the review queue and is not used until a checker settles it.
- **A row check 1 marked `wrong`** goes to the review queue. Its corrected value is also an AI reading, so it is not used until a checker approves it.

| | accepted by both | unconfirmed | review queue |
|---|---|---|---|
| Institutions (570) | 563 | 6 | 1 |
| Programmes (297 rows, 1 empty) | 281 | 2 | 14 |
| Facts (336) | 285 | 38 | 13 |
| of which high-stakes (303) | 257 | 35 | 11 |

Rows that cite a non-official copy (news, Google Drive, Facebook, Instagram, Wikipedia, a compromised board site) are never loaded as fact, whatever the checks say (R-72). These include the AJK Joint Admission Committee rows copied from educationinkarachi.net and ajkbise.net.

v4 is the version to import. v2 and v3 are kept as history.
