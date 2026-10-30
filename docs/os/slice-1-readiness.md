# PAI OS Slice 1: production readiness

Status on 2026-10-19 for the Slice 1 branch stack (`os/s1-spec` … `os/s1-t12-review-fixes`). Spec:
`docs/superpowers/specs/2026-10-18-pai-os-slice-1-design.md`. Build log with every ruling:
`docs/os/handoff/slice-1-sdd-ledger.md`.

**Short version:** the engine is production-shaped and tested: kernel, compiler, runner, revisions,
tenant scoping and the crash behaviour. **Students should not see it yet.** Email only logs, every
programme date is unconfirmed, several durations are developer estimates, and the visa step is blocked
until someone supplies a visa target date.

## 1. Ready (real behaviour, tested, no placeholders)

| Feature | Evidence |
|---|---|
| Plan compiler: backward scheduling, end-of-day in the institution's timezone, DST, critical path, slack | `tests/os/test_compiler.py`, golden test student (`test_golden.py`), checked by hand |
| Kernel as the sole writer: state machine, idempotent create, revisions, playbook upgrade, dual-write of events and enqueue requests | `test_kernel.py`, `test_states.py`, `test_invariants.py`, review fixes C1/C2/I4 |
| Task runner on DBOS: executor IDs, workflow ID `task_id:attempt`, reconcile, worker enqueues by itself | `test_runner.py`, `test_crash.py` (SIGKILL chaos: no lost or duplicated task; repeated runs green) |
| Scheduled jobs (reconciler, deadline engine, reminders, outbox delivery) fire on DBOS schedules | `test_schedule.py` (a mutation shows it can fail) |
| Tenant scoping of every read and write | `test_tenancy.py` |
| Admin API: start a plan, read a plan, upgrade it, confirm or supply facts, list open facts. Admin calls send `X-OS-Admin-Token`, because the host's session middleware rewrites `Authorization` | `test_api.py`, `test_review_fixes.py`, `tests/test_os_bridge.py` (through the real middleware) |
| Student inbox API with host read and write auth | `test_api.py`, `tests/test_os_bridge.py` |
| Fake routes run with no code change (Ireland master's, Pakistan BS) | `test_golden.py::test_fake_routes_run_unchanged` |
| Migrations: `os_0002` on an empty database, both Alembic branches, down and up again | integrated-tree check (see the Slice 1 handoff) |
| Guards: Tach boundary, kernel-only writes, no country terms in Python, timezone-aware columns | `test_boundaries.py`, `test_invariants.py`, `test_models.py` |

## 2. Works, but not for real students yet

| Feature | What is missing |
|---|---|
| Email reminders | **Mock delivery.** `OS_EMAIL_SENDER=log` only writes a log line and an `email_logged` event. Resend, the staging allow-list and a workspace-id → email lookup are not built (review M18). One failing send blocks the queue (M4). |
| Student inbox page (`/[workspace]/os-inbox`) | Only reachable by URL, with no link in the Counsellor navigation. "Choose" items have no options or payload (M10). English only. "Provide" items mark done but cannot upload (Slice 3). |
| Admin operations | A single static `OS_ADMIN_TOKEN`; no admin UI; no audit of who confirmed a fact. |
| Deployment | The `os-worker` compose service exists only behind `--profile os` on branch `chore/os-worker-compose` (to `dev`, after the gate). `OS_ENABLED` defaults to false. |

## 3. Estimates (labelled "estimated" in the inbox)

These come from playbook constants with `estimate: true`. They are not official figures; replace them
when research returns real numbers.

| Constant | Value | Basis |
|---|---|---|
| `uni_assist_lead_days` | 56 | uni-assist's own recommendation ("at least 8 weeks"), not tied to 2027 |
| `visa_processing_days` | 90 | **Developer planning buffer.** No official waiting time exists (Spike 5 C5) |
| `english_test_days` | 30 | booking + results, developer estimate |
| `hec_attestation_days` | 14 | no official processing time found (Spike 5 A1) |
| `blocked_account_days` | 21 | includes the attestation appointment, developer estimate |

## 4. Unconfirmed data (shown as "provisional")

- **Every programme fact** in `app/os/knowledge/seed/germany_ws2027.yaml` is `unconfirmed`: deadlines,
  routes and English scores for 3 programmes (TU Chemnitz Embedded Systems, OVGU EEIT, BTU AI) are leads
  from the developers' shortlist, projected to 2027 and not re-read.
- **Route amounts** (blocked account €11,904, uni-assist €75/€30) are seeded `unconfirmed`, because
  2027 figures are not published.
- **`visa_target_date` is deliberately not seeded**, so `visa_apply` and Phase D are blocked until an
  admin supplies it (`POST /v1/os/facts`).
- **HEC e-Attestation acceptance (Spike 5 A1):** the developers report yes, but there is no official
  source yet.
- Only 3 of the 30 shortlist programmes are seeded. The rest are Spike 1 / Slice 2 work.

## 5. Not built in Slice 1 (by decision or deferred)

See the Slice 1 handoff, §8, for the full list: grade converter, funds calculator, checklist
validator, real email, research agent and freshness sweeper, event-triggered deadline engine,
revision limits and the Supervisor, and the 19 deferred review minors.

## 6. Before any student uses it

1. Merge the stack and pass the Slice 0 and Slice 1 gates (both teams review the shared files).
2. Real email: Resend sender, staging allow-list, address lookup, outbox failure handling.
3. Confirm the seeded programme facts against official pages, or let Slice 2 research them. Supply
   `visa_target_date`. Replace the developer estimates where research gives real figures.
4. Deploy the `os-worker` service with a stable `OS_WORKER_ID` per replica and set `OS_ENABLED`,
   `OS_ADMIN_TOKEN`.
5. Add a navigation entry for the inbox page, and options for "choose" items.
