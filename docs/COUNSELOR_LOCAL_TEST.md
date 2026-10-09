# Founder checklist: local Counselor

From the single `PAI-OS/workspace` checkout on `dev`, keep existing backend
credentials in the ignored `.env`. Choose supported `PAI_COUNSELOR_MODEL`,
`PAI_ANALYST_MODEL`, `PAI_SENSITIVE_CHECK_MODEL`, `PAI_MIRROR_MODEL` and
`PAI_ROADMAP_MODEL`; see the measured recommendations in `eval_reports/`.
Never put permanent keys in the frontend. This checklist does not change `.env`.

## Start

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

Open http://localhost:3000 and sign in. Backend **and worker** must run.
Use the same project name to keep your database. Migrations 096–100 cover
Notebook, noted questions, Mirror, sourced answers and roadmap lane identity.

## Test as a student

- Start a fresh conversation with a goal. Share completed/current education,
  what you have actually tried, family concerns, time and budget constraints.
- Expect a natural reflection and one useful question at a time. No route plan,
  unsupported admission claims, identity re-asks or repeated education loop.
- Correct an education claim; inspect Profile. Conflicting statements must go
  through Vault reconciliation, not silently replace accepted facts.
- Upload a document and inspect extracted evidence/verification. Analyst notes
  remain private; student Profile still uses the existing Vault.
- Switch text ? voice ? text. The conversation and Profile stay shared. Interrupt
  speech, end the call, and reconnect. Check no internal JSON is displayed/spoken.

## Mirror

- Once discovery is sufficient, wait for the background Mirror card.
- Expand dimensions; every known picture has your supporting evidence. Unknowns
  must be honest. Lanes reflect your wishes, strengths and limits.
- **Edit:** correct a detail. Expect discovery to resume and a revised card later.
- **Confirm:** confirm the current version. Repeated clicks must not queue duplicate
  research. Research begins only after confirmation.

## Roadmaps

- Wait for light research and open Roadmaps. Expect one card per confirmed lane.
- Inspect personal fit, action test, gaps, steps and cited sources. Every external
  requirement/timing/number must have evidence. Your own numbers/action targets
  need no research citation. Each fact shows verified or unconfirmed honestly.
- A cited unconfirmed fact alone must not block a ready card. Missing decisive
  information should identify the gap as needs_info, never invent an answer.
- Choose/rethink a route; inspect that your choice persists. Add your own route.
- Report an outdated source; expect a stale marker and bounded refresh, with your
  annotations preserved. A new confirmed Mirror receives a new research allowance.

## If something fails

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml logs --tail 100 backend worker migrate
```

Record the screen, time, conversation and expected result; redact credentials.
Manual model/voice/document/research use can incur charges. For a provider-free
check, use the fake-provider procedure in
[counselor/CLEANUP_AFTER_DEEP.md](counselor/CLEANUP_AFTER_DEEP.md#reproducible-offline-startup-check).
Automated suites use fake models. This checklist is not a claim that a founder
manual acceptance session has already been completed.

## Stop without deleting data

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml down
```

Rollback reference: `legacy-counselor-final` (requires compatible deployment and
schema review; do not delete database volumes to roll back).
