# Local deep Counselor testing

Use the single `PAI-OS/workspace` checkout. Start PR branches from latest `dev`,
open PRs into `dev`, then return the folder to latest `dev` after delivery.
Deep is the sole Counselor; there is no legacy mode flag. The rollback tag is
`legacy-counselor-final`.

## Environment

In the ignored local `.env`, keep the existing backend provider/API-key settings
and select models supported by that provider:

```dotenv
PAI_ENABLED=true
PAI_COUNSELOR_MODEL=<strong-model-id>
PAI_ANALYST_MODEL=<cheaper-model-id>
PAI_SENSITIVE_CHECK_MODEL=<safety-check-model-id>
```

Replace the placeholders. The sensitive-check model is for the pre-Mirror helper,
not a per-turn call. If unset, Analyst defaults to Counselor and the sensitive
checker defaults to Analyst. Permanent keys belong only on the backend.

## Start and stop

From `PAI-OS/workspace`:

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

Open `http://localhost:3000`. Keep this project name to reuse its database and
storage volumes. Migrations include `096_counselor_notebooks` and
`097_counselor_noted_questions`. If another stack occupies ports 3000/8000, stop
that stack first. Stop this stack without deleting its volumes:

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml down
```

## What to test now

Test counseling only: state a goal, explain current and previous education,
correct a fact, and continue the same conversation through text and voice.
Check Profile and document intake through the existing Vault reconciliation flow.
Background Analyst notes are private and separate from accepted Profile facts;
async jobs can finish after a reply has appeared.

The new deep Mirror, its confirmation, and roadmaps generated from that Mirror
are not available yet (PR 6-8). Questions are noted rather than researched during
counseling. Existing Roadmaps still loads. Existing PAI OS surfaces are unchanged;
they are outside this counseling test scope.

Automated tests use fake models/recorded fixtures. Manual chat, voice and document
processing can call configured providers and incur charges; do not use them when
real API calls are prohibited. For a provider-free startup check, use the isolated
fake-provider procedure in [the consolidation record](counselor/CLEANUP_AFTER_DEEP.md#reproducible-offline-startup-check).
