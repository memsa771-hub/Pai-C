# Beta runbook (29 Oct 2026)

How to run and watch the beta. Spec: [BETA_CONVERSATION_SPEC.md](BETA_CONVERSATION_SPEC.md). Build detail and limits: [BUILD_REPORT_V1.md](BUILD_REPORT_V1.md).

## 1. Set the environment

Edit `.env`. Only names are listed here; values are the founder's. `.env.example` shows every name.

| Name | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | chat (Sonnet 5.5). Without it chat runs on OpenAI and logs one warning. |
| `PAI_API_KEY` | OpenAI key for extraction, analysis and research. |
| `MEMORY_EMBEDDING_API_KEY` | embeddings. Without it recall is lexical; nothing breaks. |
| `PAI_FOUNDER_EMAILS` | comma-separated sign-in emails allowed to read `/v1/admin/usage` and see the Settings spend card. |
| `PAI_MONTHLY_CAP_USD` | total model and web spend cap per UTC month (default 100; 0 pauses every gated role, the safety roles still run). |
| `PAI_COUNSELOR_PROVIDER`, `PAI_COUNSELOR_MODEL` | `anthropic`, `claude-sonnet-5-5`. |
| `PAI_ANALYST_MODEL`, `PAI_MIRROR_MODEL`, `PAI_RESEARCHER_MODEL` | `gpt-5`. |
| `PAI_PLANNER_MODEL` | `gpt-5-mini` (the planner runs on every turn). |
| `PAI_PATH_ANALYSIS_MAX_PER_DAY`, `PAI_MIRROR_TEXT_MAX_PER_DAY` | optional; model runs per workspace and day, default 6 each. |
| `PAI_DEFAULT_COUNTRY` | optional; catalog country code for students whose Vault names none (default `pk`). |
| `PAI_PROPOSALS_DIR` | set by docker-compose to `/app/proposals` (host `./proposals`). |
| `PAI_SEMANTIC_RECALL_ENABLED` | `true`. |
| `PAI_FIELD_NOTE_DAYS`, `PAI_RULES_REFRESH_MAX_CALLS` | optional; defaults 90 and 60. |

## 2. Start

~~~powershell
python scripts/run.py
~~~

It rebuilds only what changed, runs Alembic to head (this release adds 123 and 124) and opens http://localhost:3000. `python scripts/run.py --fresh` starts with an empty database. Before the first shared run, round-trip migrations 120 to 124 on Postgres (upgrade, downgrade to 119, upgrade). This has not been done yet.

## 3. Watch spend

- Settings > Account shows the month's spend against the cap, the stage and spend per role (founder emails only).
- `GET /v1/admin/usage` with the Firebase bearer returns `{month, cap, spent, stage, by_role}`. Stage is `ok`, `research_paused` (80 %) or `paused` (100 %).
- Spend is an estimate from `backend/app/pai_c/policy/model_costs.json`. Keep its rates in line with the providers' price lists (`backend/scripts/eval/model_prices.json` has the same rows for the eval scripts). Web searches and page reads are priced per call (`usd_per_call`) and show as role `web`.

## 4. When the cap pauses

- `research_paused` (80 %): the path analyzer, Mirror text, field notes, path research and rules refresh skip quietly. Chat and extraction continue. Runs resume when the month rolls over or the cap is raised.
- `paused` (100 %): the chat reply (and a new student's opening) is only the paused line, in the student's chat language when it was rendered before the cap (it is rendered once at 80 %), else in English; extraction stops. Wellbeing replies still work.
- To resume: raise `PAI_MONTHLY_CAP_USD` in `.env` and rerun `python scripts/run.py` (only the changed containers restart). Check that `/v1/admin/usage` shows `ok`.

## 5. Extraction evaluation

From `backend/`:

~~~powershell
python -m scripts.eval_extraction --live --cap-usd 5
python -m scripts.eval_extraction --replay
~~~

`--live` runs the 16 golden cases through the real extractor and never spends above the cap. It saves recordings and prints recall and precision, and exits 1 below 90 % core recall (`--min-recall`). `--replay` rescores the recordings at no cost. One of the two flags is required.

## 6. Rules and calendar refresh

The monthly job runs by itself. To run it now, from `backend/`:

~~~powershell
python -m scripts.run_rules_refresh
~~~

The job in Docker writes `./proposals/<date>.json` on the host (docker-compose mounts `./proposals` at `/app/proposals` and sets `PAI_PROPOSALS_DIR`); a second run the same day writes `<date>-2.json`. A run on the host without `PAI_PROPOSALS_DIR` writes to `backend/app/pai_c/policy/refresh_proposals/`. No policy file changes. Check each diff's quote and source against the official page, then, from `backend/` on the host checkout:

~~~powershell
python -m scripts.apply_refresh ../proposals/<date>.json [--only PATH ...]
~~~

A bare file name is looked up in `PAI_PROPOSALS_DIR` (or the policy folder) and in the repository's `./proposals`; with no name, `python -m scripts.apply_refresh` applies the newest proposal in either, so a host run finds the Docker worker's proposals without any setting.

A diff whose file value has changed since is reported stale and skipped. The admission-rule and calendar tests run after applying; if they fail, every file is restored. Commit the changed policy files yourself.

## 7. Where things land

- Proposals: `./proposals/` on the host (Docker), or `backend/app/pai_c/policy/refresh_proposals/` for host runs. Proposal files are git-ignored.
- Field notes: table `pai_field_notes`, one row per field and country, refreshed after 90 days.
- Extraction recordings: the `recordings/` folder the eval script creates.

## 8. Known limits

- A field-note fact whose quote uses its number in another sense still passes the check.
- The calendar is secondary-sourced for most regions. Gaps: GB, AJK, AKU-EB HSSC, Sindh and KP HSSC months. Affected students see an uncertain time.
- The Mirror text does not re-render when only the chat language changes.
- The first applied proposal reformats `admission_rules.json`.
- The institution filter is a word list plus catalog names.
- The Settings spend card hides itself after a failed first load in a browser session.
- Cost estimate after the final fixes (Sonnet at $2/$10 with the static voice prompt cached as its own system block (the per-turn context is not cached), thinking off at effort low, planner on gpt-5-mini, path analysis and Mirror text at 6 runs per workspace and day, web calls counted): about $1.5–2 per student over 30 turns, so the $100 cap covers roughly 50–65 such students. The 80 % stage (path analysis, planner, Mirror text and research stop for everyone) comes earlier. For a larger cohort the founder may raise `PAI_MONTHLY_CAP_USD`. Task 7 must measure the real figure.
- The monthly cap is not a hard ceiling: the classifier, safety, summarizer and sensitive check still run at 100 %.
- A chat-asked path analysis is not held by the daily cap (only by the 80 % stage).
- Live end-to-end verification with real models (Task 7) is pending; run it before inviting students.
