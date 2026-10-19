# Spike 1: research of the 30 shortlist programmes — design

Status: approved (owner: "ok carry on", option A) · 2026-10-19 · Result: PASS, see `spike1-report.md` · Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md`
(the parent wins on any conflict). Comes before the Slice 2 spec (parent §5: Spike 1 runs before Slice 2).

## 1. What the spike must show

Parent §5, row 1: the research agent, run on the 30 programmes, gets **≥95% of the facts it marks
`confirmed` correct**, and **≥70% of the facts reach `confirmed`**. If it fails: more facts are shown
unconfirmed, or the pilot uses fewer programmes.

It tests the parent's research trust flow (§3.2): a fact is `confirmed` only if (1) it comes from an
official source, (2) two independent readings with different prompts agree, and (3) it belongs to the
target intake. The spike also answers the cost question for research (§9: about $190 a year to keep
30 programmes researched).

## 2. Inputs

- **Answer key:** `backend/tests/os/quality/spike1_answer_key.yaml`, 30 programmes × 11 fields,
  transcribed from the developers' checks in `docs/os/spikes/PAI-OS-Programme-Shortlist-WS2027-verified.xlsx`
  (21 confirmed, 6 corrected, 3 needing follow-up). It is a permanent quality set (parent §5) and has a
  shape test (`tests/os/test_spike1_answer_key.py`), which also checks that the Slice 1 seed agrees with it.
- **Programme list:** university, programme name and a start URL per programme. The start URL is the
  official programme page from the answer key's `sources` (DAAD only where no official page is known).
  Production gets the same thing from the programme list's `programme_page_url` (Spike 5 §3).

## 3. Decisions

| # | Decision | Proposal |
|---|---|---|
| SP1-D1 | **Which intake counts** (trust rule 3) | **Option A (owner, 2026-10-19).** Run now with `--min-cycle 2026`: a date or amount counts only if its quote or cycle names 2026 or later and that year appears on the page. Re-run with `--min-cycle 2027` once WS 2027/28 is published (Feb–Mar 2027). Procedural facts need no year (Spike 5 §1). See §6. |
| SP1-D2 | Fields scored | The 11 fields in the answer key: language, tuition, semester contribution, deadline open and close, route, English, German, grade, admission test, intakes. These are what the compiler and the inbox need first (Spike 5 §3). The other Spike 5 fields are extracted but not scored. |
| SP1-D3 | Code location | `backend/spikes/spike1/`, throwaway like Spike 3. The fetcher, robots check, quote check and normalisers are written so Slice 2 can lift them into `app/os/knowledge/`. The answer key stays forever. |
| SP1-D4 | Reading pages | `httpx` with `robots.txt` respected (parent F14; a 401/403 robots file means disallow all) and an identifying user agent. One try per page: no retry code (invariant 7). **Ruling:** HTML goes through the standard-library parser and PDF through `pypdf` (already a dependency), not Docling: Docling needs a `requirements.txt` change, a shared file that would have to reach `dev`, and nothing merges into `dev` for now. The Slice 2 spec decides on Docling. Each page is cached on disk, so both readings see the same text and a re-run costs nothing to fetch. Blocked pages are logged; their facts stay unconfirmed. |
| SP1-D5 | Page budget | **Ruling:** links are ranked by rule, not by the agent (one right answer, parent §3): from the start URLs, follow at most 5 links on the **university's own domains** whose URL or anchor names an application topic. Shared hubs (DAAD and uni-assist general pages), login portals and links that wrap another URL are skipped: in the dry run they took most slots. Up to 60,000 characters per programme reach the model (15,000 per page, start pages first). No web search in Spike 1: it needs a Tavily or Brave key, and the start URL is what production will have. |
| SP1-D6 | Readings | Reading A: one extraction prompt over the page set, giving every field with a value, the exact quote, the URL and the cycle the page names. Reading B: a different system prompt that asks per field group as questions. **Ruling (after runs 1–8, report):** when A or B gives no valid reading for some field, reading C (a third prompt, an audit checklist) runs once for the programme. All use the `cheap` tier (`gpt-5.4-mini`, D8). Output is a Pydantic model; repair through output validation, max 2 (invariant 7). |
| SP1-D7 | Deterministic checks (no AI) | A fact becomes `confirmed` only if: (a) its URL's domain is official (the university's own domain, `uni-assist.de`, `daad.de`, or DAAD's `myguide.de`), (b) its quote appears in the cached page text (whitespace- and case-normalised), as one passage or as pieces split at line breaks or "..." that appear in order within 400 characters (a table row or a cut passage); otherwise the reading is dropped as a fabricated quote; (c) at least two readings are valid and **every** valid reading agrees after normalisation (§4): reading C fills a gap, never outvotes, and (d) the cycle rule of SP1-D1 holds. Anything else is `unconfirmed` with its source link. Two official pages that disagree give `unconfirmed` with a `conflict_note` (S1-D6). |
| SP1-D8 | Runs | A test-model run in CI over recorded pages (fast, free) proves the harness. The pass-bar run is a billed run by a developer with `OS_OPENAI_API_KEY`, like Spike 3. |

## 4. Scoring

- **Scored facts:** answer-key fields whose value is not null, in rows with `key_status: confirmed`,
  excluding `open_fields`. The 3 follow-up rows, the conflict row and open fields are reported
  separately; they are also where the agent may settle what the developers could not.
- **Correct rate** = agent-confirmed scored facts that match the key ÷ agent-confirmed scored facts.
  A fact the agent confirms where the key is null is **not scored**: the developers' notes often leave a
  field out without meaning the page says nothing. Such facts are listed as `extras_for_review`.
  **Pass: ≥ 0.95.**
- **Confirmed rate** = agent-confirmed scored facts ÷ scored facts. **Pass: ≥ 0.70.**
- **Matching**, per field:
  - Route, language, German level and intakes: exact (sets for intakes).
  - Deadlines: the same `MM-DD`.
  - Tuition: exact. Semester contribution: within 10% when the key says `approx`, otherwise within €1.
  - English: every score the key gives (IELTS, TOEFL iBT, PTE, CEFR, MOI accepted) must match exactly;
    scores the key does not give are not scored.
  - Grade: `german_max` and `percent_min` exact.
  - Admission test: present vs. null, and the set of named tests (TestAS, GATE, GRE, dMat).
- **Also reported:** per-field accuracy, dropped quotes (fabrication rate), pages refused by robots
  or blocks, tokens and cost per programme, wall time.

## 5. Cost estimate

30 programmes × 2 readings × up to ~15k input tokens ≈ 0.9M input tokens ($0.68 at $0.75/M) plus
~100k output tokens ($0.45 at $4.50/M): **about $1.10 a run** (repairs add a little). Measured: $0.72–0.77 with two readings, $1.01–1.05 with reading C (report). Re-checking the
30 programmes twice before each deadline (30 and 7 days, parent §3.2) stays far under the §9 estimate.

## 6. Why option A (SP1-D1)

According to the developers' checks (October 2026), only 2 of the 30 programmes (BTU Artificial Intelligence and BTU Micro- and
Nanoelectronics) publish WS 2027/28 dates. Under trust rule 3 as written, almost every date fact is
`unconfirmed` today, so the ≥70% confirmed bar fails by construction, whatever the agent's quality.

| Option | What it means | Cost |
|---|---|---|
| **A (chosen)** | Run now with "target intake" = the cycle the page shows. This measures what the spike is for: reading accuracy and the trust checks. The intake rule is still applied and tested; it just takes the current cycle as its target. Re-run in Feb–Mar 2027 with WS 2027/28 as the gate for real pilot data. | One extra run (~$2). |
| B | Run now with WS 2027/28 strictly. | The confirmed-rate bar fails; the result says little about the agent. |
| C | Wait until the WS 2027/28 pages exist (Feb–Mar 2027). | Slice 2 waits about four months; Tier B deadlines (Apr–May 2027) leave little time after that. |

## 7. Done when

- The harness runs end to end on the test model in CI (recorded pages, scoring checked against a
  hand-made result).
- The billed run report (`docs/os/spikes/spike1-report.md`) gives both rates, per-field results and the
  cost, with a verdict against the pass mark, signed by both developers.
- Lessons for the Slice 2 spec are written into the report: prompts, page budget, blocked sites, and
  whether a `conflict` status is needed (Spike 5 open point 4).

## 8. Dry run (2026-10-19, test model, live pages, no API cost)

`python -m spikes.spike1.run --model test` fetched 175 pages for the 30 programmes in 18 s (cached);
every programme has readable pages. Findings that the billed run and Slice 2 inherit:

- **Dead links in the key's sources:** DAAD detail 4492 (HSRW Mechanical Engineering) and
  `hochschule-rhein-waal.de/en/node/6903` return 404; HSRW gets two current master's application pages
  as extra start pages (`EXTRA_START_URLS`). The developers should add each HSRW programme's own page.
  `tu-freiberg.de/media/2369/download` (the brochure) also returns 404.
- **Refused by robots.txt:** the HISinOne application portals (TU Chemnitz, Siegen `unisono`). They are
  application forms, not fact pages.
- **Timeouts:** two hs-anhalt.de pages (one try only); other Anhalt pages were read.
- **Not blocked, contrary to Spike 5 §4:** `www2.daad.de` detail pages were readable.
- **Weak inputs:** Hof has only its myGUIDE page (no own domain known; the row is excluded anyway);
  Saarland, TU Ilmenau and TU Dortmund start from DAAD only and rely on links to their own domains.
