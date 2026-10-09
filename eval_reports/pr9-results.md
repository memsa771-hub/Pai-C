# PR 9: controlled evaluation results (2026-10-09)

## Smoke comparison: the two authorized runs

| Model, effort | Turns | Estimated cost USD | p50 ms | p95 ms | Multiple questions | Invalid JSON | Blocked script |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-6-sol, low | 8 | 0.0141 | 2429 | 3796.8 | 0 | 0 | 0 |
| gpt-6-astra, low | 8 | 0.0616 | 3568 | 4191.4 | 0 | 0 | 0 |

Both stayed under their individual $0.50 caps. Full smoke transcripts and tokens:
[Sol](pr9-smoke-sol.json), [Astra](pr9-smoke-astra.json).
One distinct question in every smoke reply; no admission plan or invented world
fact observed in these 16 replies. Smoke context is synthetic and does not test
Notebook updates, Mirror readiness or roadmap grounding.

Pricing verified against the official model pages on 2026-10-09:
[Sol](https://developers.openai.com/api/docs/models/gpt-6-sol),
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Mini](https://developers.openai.com/api/docs/models/gpt-5-mini).
Tavily basic search is budgeted at
[$0.008/request](https://docs.tavily.com/documentation/api-credits).
The ledger reserves uncached/cache-write and regional-premium upper estimates
before each request, bounds completion including reasoning and disables SDK retries.

## The ONE consolidated live run: INCOMPLETE, not a release pass

Requested personas: Danish (Pakistan), impatient (Indonesia), working adult
(Philippines). Counselor/Mirror/roadmap model: Sol low; Analyst: Mini medium;
simulator, memory, sensitive checker and grader: Mini. Shared hard cap: $3.
No .env edits. No second run or provider retry was performed.

The run aborted on an empty grader response (JSONDecodeError). The previous
harness wrote reports only at the end, so its in-memory ledger and transcript
were lost when the disposable container exited. Exact consolidated spend and
per-student costs are unavailable; the pre-call guard bounded spend by $3.
Do not substitute this ceiling for measured cost. No reliable consolidated
latency or complete transcript is available. The second and third personas and
the end-to-end Mirror/research/roadmap stages were not established as completed.

A read-only progress inspection during the first persona observed a Notebook in
DIRECTION, with person/education coverage true but the other six coverage flags
false. The first-persona conversation was still in progress. The simulator invented
example projects and an education stage absent from its fixture; this weakens
any quality conclusion even before the grader failure. No such observations are
claimed as a scored transcript or hidden-truth recall result.

Offline harness fixes now checkpoint token reservations/usage and partial
transcripts, retain reports on grader parse failure, and continue discovery
when a premature Mirror action is ignored. These fixes were NOT run live.

## Targets

| Target | Outcome |
| --- | --- |
| One question >=95% | Smoke PASS 16/16; consolidated NOT MEASURED |
| No advice before Mirror 100% | Smoke PASS by manual inspection; consolidated NOT MEASURED |
| No invented world facts 100% | Smoke PASS by manual inspection; consolidated NOT MEASURED |
| Hidden recall >=4/6 each | NOT MEASURED |
| First Mirror valid >=80% | NOT MEASURED |
| Roadmaps ready >=80% | NOT MEASURED |
| Cost <=$1/student | NOT MEASURED; consolidated cap was $3 total |
| p50<=5s, p95<=15s | Smoke PASS; consolidated NOT MEASURED |
| Blocked script 0 | Smoke PASS; consolidated NOT MEASURED |

## Model recommendation

Provisional: PAI_COUNSELOR_MODEL=gpt-6-sol with low reasoning: comparable smoke
quality, about 4.4x lower cost and lower latency. Mini medium is a candidate
Analyst only; this incomplete run does not approve its discovery or Mirror
readiness quality. Keep separate Mirror/roadmap model settings; Sol is an
unvalidated candidate for those stages. No final production model approval is
claimed. A new end-to-end evaluation needs separate authorization.

