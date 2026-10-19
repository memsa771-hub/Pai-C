# Spike 1: research of the 30 shortlist programmes — design

Status: draft for review · 2026-10-19 · Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md`
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
| SP1-D1 | **Which intake counts** (trust rule 3) | **Needs the owner's call — see §6.** Proposal: run now against the cycle each page currently shows (mostly WS 2026/27), and re-run against WS 2027/28 when the universities publish it (Feb–Mar 2027). |
| SP1-D2 | Fields scored | The 11 fields in the answer key: language, tuition, semester contribution, deadline open and close, route, English, German, grade, admission test, intakes. These are what the compiler and the inbox need first (Spike 5 §3). The other Spike 5 fields are extracted but not scored. |
| SP1-D3 | Code location | `backend/spikes/spike1/`, throwaway like Spike 3. The fetcher, robots check, quote check and normalisers are written so Slice 2 can lift them into `app/os/knowledge/`. The answer key stays forever. |
| SP1-D4 | Reading pages | `httpx` with `robots.txt` respected (parent F14) and an identifying user agent. HTML and PDF go through Docling to text (stack, parent §8). Each page is cached on disk per run, so both readings see the same text and a re-run costs nothing to fetch. Pages that refuse automated reading (DAAD, TU Ilmenau) are logged; their facts stay unconfirmed. |
| SP1-D5 | Page budget | From the start URL, follow at most 5 links that stay on the university's domain or uni-assist, picked by the agent from the page's links. No web search in Spike 1: it needs a Tavily or Brave key, and the start URL is what production will have. |
| SP1-D6 | Two readings | Reading A: one extraction prompt over the page set, giving every field with a value, the exact quote, the URL and the cycle the page names. Reading B: a different system prompt that asks per field group as questions. Both use the `cheap` tier (`gpt-5.4-mini`, D8). Output is a Pydantic model; repair through output validation, max 2 (invariant 7). |
| SP1-D7 | Deterministic checks (no AI) | A fact becomes `confirmed` only if: (a) its URL's domain is official (the university's own domain, `uni-assist.de`, `daad.de`), (b) its quote appears in the cached page text (whitespace- and case-normalised); otherwise the fact is dropped as a fabricated quote; (c) A and B agree after normalisation (§4), and (d) the cycle rule of SP1-D1 holds. Anything else is `unconfirmed` with its source link. Two official pages that disagree give `unconfirmed` with a `conflict_note` (S1-D6). |
| SP1-D8 | Runs | A test-model run in CI over recorded pages (fast, free) proves the harness. The pass-bar run is a billed run by a developer with `OS_OPENAI_API_KEY`, like Spike 3. |

## 4. Scoring

- **Scored facts:** answer-key fields whose value is not null, in rows with `key_status: confirmed`,
  excluding `open_fields`. The 3 follow-up rows, the conflict row and open fields are reported
  separately; they are also where the agent may settle what the developers could not.
- **Correct rate** = agent-confirmed scored facts that match the key ÷ agent-confirmed scored facts.
  A fact the agent confirms where the key says null (the page states nothing) counts as wrong.
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

About 90 pages (30 programmes × 3) × 2 readings ≈ 180 requests of ~7k input tokens ≈ 1.3M input tokens
($0.95 at $0.75/M) plus ~150k output tokens ($0.65 at $4.50/M): **about $1.60 a run.** Re-checking the
30 programmes twice before each deadline (30 and 7 days, parent §3.2) stays far under the §9 estimate.

## 6. Open point for the owner (SP1-D1)

According to the developers' checks (October 2026), only 2 of the 30 programmes (BTU Artificial Intelligence and BTU Micro- and
Nanoelectronics) publish WS 2027/28 dates. Under trust rule 3 as written, almost every date fact is
`unconfirmed` today, so the ≥70% confirmed bar fails by construction, whatever the agent's quality.

| Option | What it means | Cost |
|---|---|---|
| **A (proposed)** | Run now with "target intake" = the cycle the page shows. This measures what the spike is for: reading accuracy and the trust checks. The intake rule is still applied and tested; it just takes the current cycle as its target. Re-run in Feb–Mar 2027 with WS 2027/28 as the gate for real pilot data. | One extra run (~$2). |
| B | Run now with WS 2027/28 strictly. | The confirmed-rate bar fails; the result says little about the agent. |
| C | Wait until the WS 2027/28 pages exist (Feb–Mar 2027). | Slice 2 waits about four months; Tier B deadlines (Apr–May 2027) leave little time after that. |

## 7. Done when

- The harness runs end to end on the test model in CI (recorded pages, scoring checked against a
  hand-made result).
- The billed run report (`docs/os/spikes/spike1-report.md`) gives both rates, per-field results and the
  cost, with a verdict against the pass mark, signed by both developers.
- Lessons for the Slice 2 spec are written into the report: prompts, page budget, blocked sites, and
  whether a `conflict` status is needed (Spike 5 open point 4).
