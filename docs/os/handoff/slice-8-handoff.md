# PAI OS handoff: Slice 8 (the Counsellor connection) built (2026-10-26)

**A new session reads this file first, all of it.** It continues `slice-7-handoff.md` (and through it the earlier
handoffs), which still hold the environment, people, rules and history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 8 spec > Slice 8 plan > the rulings in the PRs > this handoff.
- **Slice 8 spec and plan:** `docs/superpowers/specs/2026-10-25-pai-os-slice-8-design.md`,
  `docs/superpowers/plans/2026-10-25-pai-os-slice-8.md` (#142).
- **For the Counsellor team:** `docs/os/handoff/counsellor-handover.md` (their 8 steps; their gate).

## 1. Where things stand

Slice 8 is built, **switched off**: the `os_modules` row `counsellor` is `enabled = false`, and a missing row also
means off. The pilot (Slice 9) runs standalone. One PR per task, each targeting `pai-os`, merged in order:

| Order | Branch | PR | What |
|---|---|---|---|
| 0 | `os/s8-spec` | #142 | Spec and plan |
| — | `os/fix-replan-crash-race` | #143 | The replan crash test kills workers while replans are in flight (a CI race) |
| — | `os/fix-clean-deadlock` | #144 | `clean` retries its TRUNCATE after losing a deadlock to a leftover DBOS thread |
| 1 | `os/s8-t1-tables` | #145 | `os_0013`: intake, sweep mark, `closed` plan status, support-case delivery columns, the module row |
| 2 | `os/s8-t2-ports` | #146 | `app/os/ports/`, the `EscalationSink` port, the standalone adapter |
| 3 | `os/s8-t3-contracts` | #147 | Frozen v1 contracts: decision record, plan summary, escalation, programme list; samples |
| 4 | `os/s8-t4-intake` | #148 | A decision → plan, revision, replacement (`Kernel.close_plan`) or one of six refusals |
| 5 | `os/s8-t5-intake-job` | #149 | `submit_counsellor_decision`; the worker's `counsellor.intake` workflow and one-minute job |
| 6 | `os/s8-t6-summary` | #150 | `plan_summary` and `programme_list` |
| 7 | `os/s8-t7-escalations` | #151 | Route problems to the Counsellor through the outbox; the support page shows it |
| 8 | `os/s8-t8-glue` | #152 | `backend/app/pai_os_bridge.py` + `main.py` (shared: @memsa771-hub reviews) |
| 9 | `os/s8-t9-gate` | (this) | The gate, the intake crash test, the Counsellor hand-over, this handoff |

- **Never open or prepare a `pai-os` → `dev` PR.** The owners merge once, at the very end.
- `merge-test` (local only, `~/Pai-C-merge-test`) now carries every Slice 8 commit on top of the trial merge with
  `pai-c`. **Never push it.**

RESULTS_PLACEHOLDER

### What Slice 8 built
- **Route in:**
  - The host calls `submit_counsellor_decision(export)`, which only stores it (`os_counsellor_intake`, one row per
    decision).
  - The worker's one-minute job runs only while the module is on. It takes each student's oldest pending decision
    through `counsellor.intake` (`process`, then `finish`).
  - **Same route** (`external_ref = journey:destination:level`) → a revision of the same plan; done tasks are kept.
  - **New country or level** → the old plan is `closed` (open tasks cancelled, cause `superseded:<id>`) and a new
    plan starts.
  - **Refusals:** `not_authorized`, `invalid_export`, `route_not_supported`, `unknown_programme` (these four are told
    to the Counsellor as `other`), and `self_serve_plan_open`, `plan_closed` (a support case).
- **Summary out:** `plan_summary(student_ref)`. It comes from the newest open plan (else the newest finished one;
  never a closed one) and gives four states, the next 3 deadlines with time zones, what waits on the student, blocked
  steps with codes only, and whether a support case is open. Also `programme_list(route_key, intake)`.
- **Escalations out:**
  - Every support case goes through `EscalationSink`: the standalone sink opens the case, and the Counsellor sink
    acts only with the module on, on Counsellor plans, for route problems.
  - It writes an `EscalationV1` row on outbox channel `counsellor` with a fixed note from `notes.yaml`.
  - The glue delivers it to the Counsellor's `/v1/escalations` and marks it `sent` or `refused` (a refused case stays
    open).
  - The email sender skips that channel.
- **The glue** (`backend/app/pai_os_bridge.py`, host code):
  - `decision_changed`;
  - `sweep_once` every 5 minutes from `main.py`'s lifespan, only when PAI OS is mounted;
  - `current_export`, which is `None` until the Counsellor builds `app/pai_c/os_export.py`.

## 2. Rulings (binding unless the owners change them; each is in its PR)
- A missing `counsellor` module row means off (#145). Downgrading below `os_0013` turns `closed` plans into `done`
  (#145).
- The frozen word lists (intake statuses, the six refusals, delivery statuses, the five reasons) are database checks
  (#145).
- The ports module imports the API for type hints only. `Replanner` takes its sink as an argument; the worker has no
  mounted services (#146).
- `EscalationV1` has both `key` and a nullable `case_id`: intake refusals have no case (#147). `schema_` in Python is
  `schema` in JSON (#147).
- The support case for `self_serve_plan_open` / `plan_closed` names a `counsellor_intake` event, which is not a
  replan type, so a repeat finds the same case (#148). A `CompileError` on a valid export is `route_not_supported`
  (#148).
- Each student's oldest pending decision per tick, so decisions run in `chosen_at` order. The workflow doesn't
  re-check the switch (a workflow ID runs once). Submit doesn't enqueue (#149).
- A blocked reason is shown only as a code, else `blocked`. `build_summary` takes `now` (#150).
- "Supervisor unavailable" is a system problem. A plan that no longer compiles is `not_eligible` whatever the event.
  The worker's replanner uses the same composite sink. `api.ts` is unchanged (#151).
- Until the Counsellor's endpoint takes the five reasons, `not_eligible`, `deadline_passed` and `other` go as
  `route_not_possible`. The glue calls `escalate()` directly with the token check (#152).
- The intake crash test takes its row lock only after the worker is up: DBOS's startup migrations wait for open
  transactions (this PR).

## 3. Deferred minors (for the final review)
1. Paths other than the intake (the replan job, admin retries) don't refuse to revise a closed plan. Every task on it
   is cancelled, so nothing runs (#148).
2. A decision whose workflow fails for good stays `pending` and blocks that student's later decisions (#149).
3. Two API replicas sweeping at the same moment could both deliver one escalation; the second's 409 would mark it
   `refused` (#152).

REVIEW_PLACEHOLDER

## 4. Open items for the owners
1. **The pilot gate (S8-D3):** confirm that the pilot opens when Slice 8 passes on the PAI OS side. The Counsellor
   side is its own gate before switching on. This amends the PAI OS board and D3.
2. **Counsellor routes after the pilot** (Matric/FSc/O-A level → BS in Pakistan, then others): a v2 scope change
   (parent §2), recorded when the time comes.
3. **The real merge:** where production setup lives now that `pai-c` deleted `docker-compose.prod.yml`, and when
   `pai-c` and `pai-os` meet.
4. **The old-OS inventory** is refreshed at the real merge with the Counsellor lead (22 modules deleted on `pai-c`,
   4 new ones need a fate). `app.routers.escalations` is now `keep` (the glue calls it).
5. **Hand the Counsellor team `counsellor-handover.md`.** Their reply of 2026-10-25 ("agreed in principle") is covered:
   nationality is optional; fall and spring are allowed; PK→PK is not plannable yet; the programme-list function
   exists; a new country or level closes the old plan and starts a new one.

## 5. Next: Slice 9, the pilot (standalone)
The pilot runs self-serve on the Germany master's route with the Counsellor module off. Switching it on waits for the
Counsellor team's gate (`counsellor-handover.md`) and the owners.
