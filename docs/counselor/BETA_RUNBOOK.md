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
| `PAI_MONTHLY_CAP_USD` | total model spend cap per UTC month (default 100; 0 pauses everything). |
| `PAI_COUNSELOR_PROVIDER`, `PAI_COUNSELOR_MODEL` | `anthropic`, `claude-sonnet-5-5`. |
| `PAI_ANALYST_MODEL`, `PAI_MIRROR_MODEL`, `PAI_RESEARCHER_MODEL` | `gpt-5`. |
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
- Spend is an estimate from `backend/app/pai_c/policy/model_costs.json`. Keep its rates in line with the providers' price lists. `backend/scripts/eval/model_prices.json` still needs `gpt-5` and `claude-sonnet-5-5` rows.

## 4. When the cap pauses

- `research_paused` (80 %): the path analyzer, Mirror text, field notes, path research and rules refresh skip quietly. Chat and extraction continue. Runs resume when the month rolls over or the cap is raised.
- `paused` (100 %): chat replies are the fixed fallback plus "PAI is paused for the month"; extraction stops. Wellbeing replies still work.
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

It writes `backend/app/pai_c/policy/refresh_proposals/<date>.json` (a second run the same day writes `<date>-2.json`) and changes no policy file. Check each diff's quote and source against the official page, then, from `backend/`:

~~~powershell
python -m scripts.apply_refresh app/pai_c/policy/refresh_proposals/<date>.json [--only PATH ...]
~~~

A diff whose file value has changed since is reported stale and skipped. The admission-rule and calendar tests run after applying; if they fail, every file is restored. Commit the changed policy files yourself.

## 7. Where things land

- Proposals: `backend/app/pai_c/policy/refresh_proposals/`. In a container this folder is inside the image, so run the scripts on a host checkout or mount the folder.
- Field notes: table `pai_field_notes`, one row per field and country, refreshed after 90 days.
- Extraction recordings: the `recordings/` folder the eval script creates.

## 8. Known limits

- A field-note fact whose quote uses its number in another sense still passes the check.
- The calendar is secondary-sourced for most regions. Gaps: GB, AJK, AKU-EB HSSC, Sindh and KP HSSC months. Affected students see an uncertain time.
- The Mirror text does not re-render when only the chat language changes.
- Proposals are written inside the app package; the first applied proposal reformats `admission_rules.json`.
- The institution filter is a word list plus catalog names.
- The Settings spend card hides itself after a failed first load in a browser session.
- Live end-to-end verification with real models (Task 7) is pending; run it before inviting students.
