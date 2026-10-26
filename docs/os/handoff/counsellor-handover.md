# PAI OS ↔ Counsellor: what the Counsellor team builds (Slice 8 hand-over)

**For the Counsellor (PAI C) team.** PAI OS has built its side of the connection and the glue
(`backend/app/pai_os_bridge.py`). The connection is **switched off**: the `os_modules` row `counsellor` is
`enabled = false`. This page lists what your side needs before anyone switches it on. It is your gate (PAI OS
Slice 8 spec §11, S8-D3); switching on is the owners' decision after it passes.

Everything here uses fictional data only. Contract changes need both developers' sign-off (both boards).

## The three channels, in one picture
1. **Route in:** the student chooses at "Where to study". Your export function builds a decision record
   (`pai.decision_record.v1`). You call `decision_changed(workspace_id)`, and the glue hands the export to PAI OS,
   which plans it.
2. **Summary out:** your Plan (J) screen asks `plan_summary(student_ref)` and shows it in the Counsellor's voice.
3. **Escalations out:** when a student's PAI OS plan hits a route problem, the glue calls your existing
   `POST /v1/escalations` code with the service token. You take the student back to choosing.

PAI OS never reads your tables, and it never talks to the student directly.

## What to build (8 steps)

1. **The export function.** Create `app/pai_c/os_export.py` with
   `decision_record_v1(db, workspace_id) -> dict | None`. It returns the student's *current* decision as
   `pai.decision_record.v1` (schema: `backend/app/os/contracts/decision_record.v1.schema.json`), or `None` when there is
   none. Until this module exists, the glue answers "not ready for PAI OS" and sends nothing. The fields:
   - `decision_id`: your `DecisionRecord.id`;
   - `journey_id`;
   - `student_ref`: the workspace ID;
   - `chosen_at`, with its time zone;
   - `origin_country`: from the Vault `location.current_country`, as an ISO 3166-1 alpha-2 code, "Stated" is fine;
   - `nationality`: optional, `identity.nationality` as a code only;
   - `destination_country` (code), `level` (`foundation` | `bachelor` | `master` | `phd`), and `target_intake`
     `{term, year}` (any lowercase term: `winter`, `fall`, `spring`);
   - `programmes`: 1–5 places ranked 1..n, each a PAI OS `programme_ref` (step 3).

   Never the Truth Map, the Mirror summary or other free text: the schema refuses extra fields.
2. **Consent.** Ask the student to agree to the hand-off, and set `authorized_at`. Without it, PAI OS refuses the
   decision (`not_authorized`).
3. **"Where to study" from the PAI OS programme list.** Call `app.os.ports.plan_query.programme_list(route_key,
   intake)` (`ProgrammeListV1`). Offer those places for routes PAI OS runs. Show other places as "PAI OS can't plan
   this", and keep them out of the export. One decision is one destination, one level, one intake and 1–5 places.
   Another country or level is a new decision under the same `journey_id`: PAI OS then closes the old plan and
   starts a new one.
4. **Call the glue after a choice:** `from app.pai_os_bridge import decision_changed`, then
   `decision_changed(workspace_id, db)`. A lost call is not lost: the glue's 5-minute sweep picks up decisions chosen
   since its last run.
5. **Accept the five escalation reasons** at `POST /v1/escalations`: `not_eligible`, `all_rejected`,
   `deadline_passed`, `blocking_gap`, `other` (schema: `escalation.v1.schema.json`). Today the endpoint takes
   `route_not_possible`, `all_rejected` and `blocking_gap`, so the glue sends the other three as
   `route_not_possible` (`_TODAY` in `pai_os_bridge.py`). When you take all five, delete that mapping.
   - Answer 404 or 409 when the journey can't take an escalation. PAI OS records it as refused and keeps its support
     case open for a person.
   - `details` holds a fixed sentence per reason (`backend/app/os/adapters/counsellor/notes.yaml`), never student
     text.
6. **Show `plan_summary`** on the Plan (J) screen: `app.os.ports.plan_query.plan_summary(student_ref)`
   (`PlanSummaryV1`, schema `plan_summary.v1.schema.json`). It holds:
   - the state: `finished`, `paused`, `needs_student` or `on_track`;
   - the next 3 deadlines, with their time zones;
   - what waits on the student;
   - blocked steps, with a reason code;
   - whether a support case is open.

   It returns `None` when the student has no open or finished plan. Write the words yourselves; the summary has no
   free text.
7. **CI on `pai-c`.** Copy the `os` job from `pai-os`'s `.github/workflows/ci.yml` (Postgres service, `tach check`,
   the alembic heads check, `pytest tests/os`). Make these pass on your branch:
   - `backend/tests/os/contracts/`: the frozen schema files and the samples;
   - `backend/tests/test_pai_os_bridge.py`: the glue, including your real `/v1/escalations`;
   - your own export tests: each sample in `backend/app/os/contracts/samples/` round-trips, and your export validates
     against `decision_record.v1.schema.json`.
8. **Fix what already fails on `pai-c` alone** (found in the trial merge, spec §12):
   - `test_os_route_detachment::test_counselor_and_os_contract_routes_stay_mounted` (`/v1/fetch`);
   - 4 `tsc` errors in `inline-card.test.tsx` and `try-it-feedback.test.tsx`.

## The files you test against (frozen v1)
In `backend/app/os/contracts/`:
- `decision_record.v1.schema.json`;
- `plan_summary.v1.schema.json`;
- `escalation.v1.schema.json`;
- `programme_list.v1.schema.json`;
- `samples/*.json`, with `samples/expected.yaml` (each export's result: `planned`, `revised`, `replaced`, or a refusal).

A change is a v2 file plus a migration path, signed off by both teams; a v1 file never changes.

## What PAI OS refuses, and what you hear about
| PAI OS refuses | When | You hear |
|---|---|---|
| `invalid_export` | the export fails the schema | escalation `other`, by journey |
| `not_authorized` | no `authorized_at` | escalation `other` |
| `route_not_supported` | no PAI OS route for origin, destination and level (e.g. PK→PK today) | escalation `other` |
| `unknown_programme` | a place not in the PAI OS programme list | escalation `other` |
| `self_serve_plan_open` | the student already runs a self-serve plan | nothing: a PAI OS support case, a person decides |
| `plan_closed` | the route's plan was closed by an earlier change of country or level | nothing: a support case |

The first four should never happen if steps 1–3 are followed.

## At the real merge (`pai-c` meets `pai-os`)
- `app/main.py`: `pai-c` cancels `maintenance_task` where `pai-os` cancels `timer_task`. Keep yours, and keep the
  `os_sweep` start and cancel lines (tried on a local trial merge).
- The OS student reference has to be rebuilt on your Firebase access rule, and the 7 OS calls in `frontend/lib/api.ts`
  must use `authHeaders()` (spec §12). The old-OS inventory needs refreshing with the PAI OS developer (spec §10 Q4).
