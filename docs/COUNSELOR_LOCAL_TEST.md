# Local Counselor test build

The local worktree is `../counselor-complete` on branch
`feature/counselor-complete`. Its ignored `.env` has been copied from
`../workspace/.env`; the API key stays server-side. The build flag
`NEXT_PUBLIC_COUNSELOR_ONLY=true` shows Counselor, Roadmaps, Profile,
Documents, and the existing notification inbox. The OS views are hidden in
this test build; the underlying OS code is untouched.

Ports 3000, 8000, and 8080 are currently used by the existing `pai-v3-local`
stack. When ready to switch, run these PowerShell commands from `PAI-OS`:

```powershell
cd workspace
docker compose --env-file .env -f docker-compose.prod.yml -f docker-compose.local.yml down
cd ..\counselor-complete
docker compose --env-file .env -p pai-counselor-test -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

Open `http://localhost:3000`. The new Compose project has separate database
and storage volumes, so the existing workspace data remains in the stopped
stack. A fresh account/profile is needed in the test stack. To return:

```powershell
cd ..\counselor-complete
docker compose --env-file .env -p pai-counselor-test -f docker-compose.prod.yml -f docker-compose.local.yml down
cd ..\workspace
docker compose --env-file .env -f docker-compose.prod.yml -f docker-compose.local.yml up -d
```

Manual path: complete Profile foundation in Counselor, confirm the goal
summary, inspect a researched route in Roadmaps, answer one requested fact,
report a wrong requirement, retry if research fails, and choose a presented
ready route. Try a voice reply during the same Counselor conversation.
Source verification can leave a fact unconfirmed when an official domain,
current-cycle page, or corroborating observation is unavailable. This is an
intended safety result, not a verified admission conclusion.

The default backend suite and recorded persona evaluation make no model or
web API calls. A manual conversation or live research test uses the configured
providers and can incur API charges.
