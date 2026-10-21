# Slice 3 quality gate report (Spike 2: real documents)

**Result: GATE PASSED under the owners' pilot bar (2 of 2 real-set runs ≥ 0.89, the sample set passed), with
page tiles read by the strong model.**

Rates and counts only. The real documents and their answer key never left the owner's machine
(`~/spike2-docs`). No value from them appears here, in the repo, or in any log.

## Owners' decision, 2026-10-21

At the spec's bar (≥ 0.90 of fields correct in each of 2 runs), no configuration passed both runs. The best, after
two fix rounds, was **tiles on the strong tier: 0.905 and 0.892**. The owners chose:

- **Configuration:** `mode: tiles`, `tier: strong` (gpt-5.4) in `app/os/agents/documents.v1.yaml`.
- **Pilot bar: ≥ 0.89 of fields correct per run.** 0.89 is the measured level: the lower run was 0.892.
  - Re-scored against it, with no new model calls: 0.905 ✓ and 0.892 ✓, so **2/2 PASS**.
  - The sample set's planted findings were all caught, and the consistent bundles stayed clean.
- **Why this is acceptable for the pilot:** the reader only pre-fills. **Every value is shown to the student, who
  confirms or corrects it before it enters their profile** (S3-D8), and the validators flag what fails a rule. At
  0.89, a student corrects about one field in nine.
- **Where the bar lives:** `PASS_CORRECT` in `backend/tests/os/quality/doc_scoring.py`, with this decision
  cited, and the spec §9 note. The 0.90 target stands for the re-gate (conditions below). The answer key's values
  were not changed to pass; its layout was wrapped under `documents:` and the owner verified it (see "The key").

**Conditions:**
1. **Re-gate on a larger real set before scaling past the pilot.** 18 documents (240 scored fields) is small: one
   field moves a run by about 0.4 points.
2. **Work on the weakest fields first** (the table below): the IELTS family name, writing score and TRF number;
   the passport tracking number; degree titles. The worst type is the IELTS form (0.82–0.85).
3. **The passport MRZ second line** still loses its filler characters in the middle of the line on the sample set
   (1/6 strictly correct). The check digits catch it and the student corrects it, but a position-aware repair is
   the next MRZ fix.
4. **Watch the cost** in the pilot: about $0.006–0.009 per document on the strong tier, far under the
   $0.05-per-document cap (S3-D11).

## The final configuration (MRZ fix, `fd0f895`, tiles, strong)

| Run | Correct | Ignoring punctuation (information) | Invented | Failed readings | Cost |
|---|---|---|---|---|---|
| 1 | 218 / 241 = **0.905** | 0.917 | 4 | 0 | $0.10 |
| 2 | 214 / 240 = **0.892** | 0.904 | 3 | 0 | $0.10 |
| Sample set | 322 / 327 = **0.985**, every planted finding caught | 0.997 | 0 | 0 | $0.17 |

Per type, runs 1 / 2:

| Type | Run 1 | Run 2 |
|---|---|---|
| ssc_certificate | 1.000 | 1.000 |
| hssc_certificate | 1.000 | 1.000 |
| passport | 0.919 | 0.919 |
| transcript | 0.917 | 0.917 |
| degree_certificate | 0.891 | 0.867 |
| ielts_trf | 0.853 | 0.824 |

**The fields still wrong in both runs**, with why, from the runner's categories:

| Field | Correct (run 1, run 2) | Why |
|---|---|---|
| ielts_trf.family_name | 1/3, 1/3 | other |
| ielts_trf.writing | 2/4, 2/4 | one character (a band misread) |
| passport.tracking_number | 2/4, 2/4 | other |
| transcript.degree_title | 1/3, 1/3 | punctuation 1, words missing 1 |
| degree_certificate.degree_title | 4/5, 4/5 | punctuation |
| degree_certificate.exam | 0/1, 0/1 | other |
| degree_certificate.institution | 4/5, 4/5 | words missing |
| ielts_trf.trf_number | 3/4, 2/4 | invented 1; other 1 |
| degree_certificate.serial_number | 3/4, 2/4 | invented 1; one character 1 |

Every other field was right in at least one run, and most in both. The full per-field lists are in the run output,
which holds names and counts only.

## How we got here (all runs, 2026-10-21)

| Step | Code | Configuration | Real set, run 1 / run 2 | Sample set | Cost |
|---|---|---|---|---|---|
| 1. First gate | `pai-os` `0c98f2f` | whole, cheap | 0.835 / 0.825 | 0.967 ✓ (whole, cheap) | $0.06 + $0.08 |
| | | tiles, cheap | 0.863 / 0.847 | | $0.07 |
| 2. Diagnostics | `beb26d3` (per-field breakdown, `--tier`) | tiles, cheap | 0.817 / 0.826 | | $0.06 |
| | | tiles, strong | 0.867 / 0.875 | | $0.24 |
| 3. Fix round | `7fce0df` (hints state the key's conventions) | tiles, strong | 0.904 / 0.880 | 0.969 ✓ | $0.53 |
| 4. MRZ fix | `fd0f895` (MRZ filler run padded to 44) | tiles, strong | **0.905 / 0.892** | 0.985 ✓ | $0.36 |
| | | | | **Total** | **≈ $1.40** |

What each step taught us:
- **Tiles beat whole pages** on the cheap tier (+0.02 to 0.03), and invent fewer values (3–4 per run against 6–8).
- **The strong tier adds about 0.05** over the cheap one. On its own it fixed the passport MRZ second line
  (0/3 → 3/3).
- **The same few fields were wrong with both models**, which pointed to convention, not reading. The key followed
  each hint's *example* ("…Examination, Annual 2020"; "name, city"), but the hints told the reader to copy "as
  printed". The fix round made each hint state the convention.
  - SSC and HSSC certificates went from 0.79–0.87 to **1.00**.
  - The key was read as counts only (words, digits, commas, capitals), never values.
- **The MRZ first line was wrong only by its filler count** (`punctuation` in every case). The reader now pads or
  trims a line's final run of `<` to 44 characters. This is a product fix: students' uploads get it too.
  - The passport MRZ first line went from 0–1/3 to **3/3** in both runs.

## The key

- 18 real documents with consent: degree certificates 5, IELTS forms 4, passports 4, transcripts 3, SSC 1, HSSC 1.
- Structure checked by script (field names known, no missing files), with no value shown.
- Before the first run, the owner checked the 3 uncertain items: a degree serial number, an IELTS TRF number and an
  IELTS writing score. The TRF number is unreadable to a person too, so the key holds it as absent. The owner then
  set `verified: true`.

## Settings changed with this decision

- `documents.v1.yaml`: `mode: tiles`, `tier: strong`.
- `settings.py`: the strong tier's list prices are now known: $2.50 input, $0.25 cached input and $15.00 output per
  1M tokens (gpt-5.4, under 272K context, from developers.openai.com/api/docs/pricing on 2026-10-21). Before this,
  `cost()` refused the strong tier, so a strong-tier document reading would have failed in the workflow.
