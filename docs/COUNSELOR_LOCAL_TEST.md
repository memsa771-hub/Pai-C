# Local Placement AI test build

Use the worktree for the branch under test. Counselor, Roadmaps, Profile,
Documents, Applications, Deadlines, Browser, and the existing notification
inbox are in one app. The API key stays in the ignored `.env` on the backend.
Set `PAI_COUNSELOR_MODE=deep` (the default) for the staged deep rollout;
`legacy` keeps the previous Core path. PR 1 still uses the Core conversation
path in deep mode while the new turn is built in PR 3.

From `PAI-OS/workspace`, rebuild the existing local Compose project:

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml up --build -d
```

Open `http://localhost:3000`. This preserves the existing
`pai-v3-local` database and storage volumes. If another Compose project
is using ports 3000 or 8000, stop that project first. To stop the test stack:

```powershell
docker compose --env-file .env -p pai-v3-local -f docker-compose.prod.yml -f docker-compose.local.yml down
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
