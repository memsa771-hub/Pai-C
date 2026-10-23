# Placement AI Workspace

Placement AI is a FastAPI/PostgreSQL backend with a standalone Next.js frontend.

Sign-in (Firebase Auth), the account emails and the Firebase console setup are
documented in [docs/AUTH_SESSION.md](docs/AUTH_SESSION.md).

## Run locally

Requirements: Docker Desktop and Python 3. Copy `.env.example` to `.env` and
fill in the keys (anything left out falls back to `backend/app/config.py`).

Both scripts can be double-clicked; they start Docker Desktop (as
administrator) if it is not running.

```bash
python scripts/run.py           # build what changed, start, open http://localhost:3000
python scripts/del.py           # delete every container, volume, image and build cache of this project
python scripts/run.py --fresh   # del.py + run.py in one go: empty database, everything rebuilt
```

`run.py` rebuilds and restarts only what changed: after a frontend-only edit
only the frontend image is rebuilt and only its container restarts; the
database and the other services keep running. Data in the Docker volumes is
kept. `del.py` wipes it all after a 5-second countdown (Ctrl+C cancels).

| Service  | Address                 | Notes                                        |
|----------|-------------------------|----------------------------------------------|
| frontend | http://localhost:3000   | Next.js standalone build                     |
| backend  | http://localhost:8000   | FastAPI; `/health`, `/docs`                  |
| worker   | -                       | durable job worker, same image as backend    |
| migrate  | -                       | one-shot `alembic upgrade head` before start |
| postgres | internal                | canonical store, `pgdata` volume             |
| redis    | internal                | cache and Pub/Sub only, no persistence       |
| qdrant   | internal                | rebuildable memory index, `qdrant_data`      |

Useful commands: `docker compose logs -f backend`, `docker compose ps`,
`docker compose stop`.

`NEXT_PUBLIC_*` variables are compiled into the frontend image, so rerun
`scripts/run.py` after changing them, and never put backend secrets into them.

The backend image includes Chromium for local browser tools. If every browser
operation uses Browser Fabric (`BROWSERFABRIC_API_KEY` set), put
`BACKEND_IMAGE_TARGET=cloud` in `.env` to skip Chromium and its libraries.

Back up the local database with `./scripts/backup-postgres.sh` (writes to the
ignored `backups/` directory).

## Offline Counselor tests

Install `backend/requirements.txt`, `pytest`, and `pytest-asyncio`, then run
`cd backend && python -m pytest -q`. The default selection excludes billed
`counselor_sim` and network-backed `live_research` tests. Run those markers
explicitly only when their credentials and costs are intended. Legacy runtime
tests explicitly select the legacy path; current Counselor v2 tests exercise
the shared chat and voice pipeline.

## Timers

Timers use a conditional database update committed before event delivery. This
makes claims safe across multiple Uvicorn processes and gives timer delivery
at-most-once semantics: a process failure after claim may lose a timer event,
but another process cannot deliver a duplicate.
