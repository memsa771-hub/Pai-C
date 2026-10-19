# Spike 1 report: research of the 30 shortlist programmes

**Verdict: PENDING the billed run.** Design: `docs/os/spikes/spike1-design.md`. Code:
`backend/spikes/spike1/` (how to run: its `README.md`). Answer key:
`backend/tests/os/quality/spike1_answer_key.yaml`.

## Pass bar (parent §5, row 1)

- **Correct rate** (agent-confirmed scored facts that match the key) ≥ 0.95.
- **Confirmed rate** (agent-confirmed scored facts ÷ scored facts) ≥ 0.70.

Scored facts: 197 (non-null key fields in the 25 settled rows, excluding `open_fields`).
Run with `--min-cycle 2026` (SP1-D1, option A).

## Harness checks

- `tests/os/test_spike1.py` (CI, no network, no paid model): page parsing, robots.txt, cache, link
  ranking, every trust rule, the matchers, scoring, and an end-to-end run on a fake model in which
  reading B invents a quote (it is dropped, and the fact stays unconfirmed).
- Dry run on live pages with the test model (2026-10-19): 175 pages for 30 programmes, every
  programme readable; findings in the design §8.

## Billed run (to be done by a developer)

```
OS_OPENAI_API_KEY=<PAI OS key> python -m spikes.spike1.run --model openai \
    --cache <dir> --out spike1-result.json --min-cycle 2026
```

| Field | Value |
|---|---|
| model | |
| scored / confirmed / correct | |
| correct_rate | |
| confirmed_rate | |
| fabricated_quotes | |
| reading_errors | |
| pages_read / pages_blocked | |
| input / output tokens | |
| cost_usd (printed) / cost (OpenAI usage page) | |
| elapsed_s | |
| pass bar line | |

- Per field: (from `per_field`)
- Top unconfirmed reasons: (from `unconfirmed_reasons`)
- `wrong`: each one checked against the page: agent wrong, or key wrong?
- `extras_for_review` and `unsettled_for_review`: what the agent found where the key is not settled.

If it fails: stop, find the cause in the `--out` file, fix, re-run, and update this report. Parent §5:
if it still fails, more facts are shown unconfirmed, or the pilot uses fewer programmes.

## Lessons for the Slice 2 spec

(prompts, page budget, blocked sites, Docling vs. the standard-library parser, whether a `conflict`
status is needed — Spike 5 open point 4)

## Sign-off

| Developer | Verdict | Date |
|---|---|---|
| @10Faheem | | |
| @MusawirKtk | | |
