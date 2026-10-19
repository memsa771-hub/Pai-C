# Spike 1: research of the 30 shortlist programmes

Design: `docs/os/spikes/spike1-design.md`. Answer key: `tests/os/quality/spike1_answer_key.yaml`.
Throwaway code (like Spike 3); the answer key is kept forever.

| Module | Does |
|---|---|
| `programmes.py` | The agent's inputs: names, start URLs, official domains. Never the answers. |
| `pages.py` | robots.txt, on-disk cache, HTML/PDF to text, rule-based link ranking, official-domain check |
| `agent.py` | Readings A, B and (when a field has only one valid reading) C: three system prompts, one output type (`fields.Reading`), cheap tier |
| `trust.py` | Official source, quote on the page, every valid reading agrees (at least two), cycle year → `confirmed` / `unconfirmed` / `not_found` |
| `score.py` | Matching against the key and the pass bar (≥95% correct, ≥70% confirmed) |
| `run.py` | The CLI |

## Run

From `backend/`, with the venv active:

```bash
# Harness check: live pages, no API cost (TestModel output is random, so the bar fails)
python -m spikes.spike1.run --model test --cache /tmp/spike1-pages --out /tmp/spike1-test.json

# Pass-bar run (billed, about $1.05 with reading C): needs the PAI OS key in the environment, never in chat
OS_OPENAI_API_KEY=... python -m spikes.spike1.run --model openai \
    --cache /tmp/spike1-pages --out /tmp/spike1-result.json --min-cycle 2026
```

- No database is needed. `OS_MODEL_CHEAP` picks the model (default `gpt-5.4-mini`).
- Reuse the same `--cache` for the billed run, so it reads the same pages as the dry run. Use a new
  cache directory to re-fetch.
- `--no-third` skips reading C (runs 1–8); `--rescore <out.json>` scores an earlier run against the current key with no API calls.
- `--only <ref> ...` runs some programmes; `--min-cycle 2027` is the re-run once WS 2027/28 is published.
- The command prints the summary JSON and `pass bar: PASS|FAIL (...)` (exit 1 on FAIL). The `--out` file
  has every fact's verdict, quote, URL and reasons, plus `wrong`, `extras_for_review` and
  `unsettled_for_review` for the developers.

Score over three runs, not one (a run moves by about ±0.03). Then update `docs/os/spikes/spike1-report.md`.
