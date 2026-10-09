# Counselor release targets

Targets are release gates, not claims of achieved quality. Evaluate the real turn,
Analyst, Vault, Mirror, confirmed research and published roadmap pipeline using
three diverse disposable personas. Unknown/ungraded results are NOT passes.

| Target | Threshold | Measurement |
| --- | --- | --- |
| One distinct ask per normal reply | >=95% | Semantic grader; exclude Mirror wrap-up and wellbeing |
| No advice before Mirror | 100% | No routes, plans or verdicts before reflection |
| No invented world facts | 100% | Every external claim traced to supplied research |
| Hidden-truth recall | >=4/6 for every persona | Final notebook meaning, graded against hidden facts |
| Mirror valid on first generation | >=80% | First generation passes code contract; acceptance reported separately |
| Roadmaps ready ratio | >=80% | Ready published cards / all confirmed lanes; report missing decisive fields |
| Total cost per student | <=$1.00 | All model phases, simulator, grader and paid search, including partial runs |
| Counselor latency p50 / p95 | <=5000 / <=15000 ms | Context + call + polish + dispatch + post; report pipeline latency separately |
| Language-policy violations | 0 | Configured Unicode script check after repair |

## Controlled evaluation

- Smoke: one run per requested model, <=$0.50 each; shared fixed messages.
- Consolidated live evaluation: exactly one run, three selected personas, <=$3 total.
- Every paid request reserves its worst-case cost BEFORE the call, with a provider
  output limit (including reasoning), framing overhead and disabled SDK retries.
  Ambiguous failures retain their reservation and stop the run.
- Model prices are editable in backend/scripts/eval/model_prices.json. Unverified
  prices prohibit live use. Search prices live in tool_prices.json.
- Report partial runs honestly; no continuation or retry of this release eval.
- Synthetic student confirmation does not substitute for founder acceptance.
- Transcripts, phase tokens/costs, latencies and pass/fail gates: eval_reports/.
- Local .env is never changed by the evaluation. Model recommendations are documented.
