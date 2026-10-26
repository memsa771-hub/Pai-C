# Roadmap engine spec (26 Oct 2026)

Founder decision: the Roadmaps page shows, simply and attractively, **which fields this student can actually get
into, from what PAI knows**, and how. Roadmaps are made by a separate engine, not by chat. Compare and Plan as they
are today are replaced. The old roadmap code may be removed; the new engine must be complete and correct.

## 1. What the student sees
One page, **Roadmap** (nav: Paths · Roadmap; Compare and Plan tabs are gone).

1. **Header:** "Where you can go", then one line built from the Vault: "From FSc Pre-Engineering, 78%". Link
   "Update in Vault" when education or marks are missing or wrong.
2. **Summary chips:** "3 open · 2 need a step · 1 not open".
3. **Field cards**, grouped: **You can go** · **Possible with a step** · **Not open from your group** (collapsed).
   Each card: field title, family icon, status badge, a facts row (entry test · years · marks needed vs yours),
   the path's one-line "why" (second person, from the path analyzer), and a small "Check with the university"
   note when the rule's confidence is not official.
4. **Route sheet** (tap a card): a vertical timeline **Now → What you need → Entry test → Degree (N years)**, a
   "What you need" checklist, the sources with links and the date checked, and **Choose this route**.
5. **Compare:** tick 2–3 cards, a bar "Compare (2)" opens one table. Same rows for every field: Status · Marks
   needed vs yours · Extra step · Entry test · Years · Rule confidence. On a phone the columns scroll with
   sticky row labels. No quotes, no long text.
6. **Your route** (after choosing): a card at the top of the page with the chosen field, progress (2 of 5) and the
   checklist; the student ticks steps. "Change route" un-chooses. This replaces the old Plan tab.

Empty states: no readable education → "Tell PAI your education first" (to Vault); no paths yet → "PAI is
working out your fields" (paths run on their own); bachelor's/master's student → the cards say "Undergraduate
entry rules only for now".

Places (universities) stay out of this page (workflow rule: places at stage H).

## 2. The engine
A pure, deterministic module (`backend/app/pai_c/roadmap/`). **No model call, no chat input.** It reads:
- current education from the Vault (`paths/fields.py`: `current_education`, `read_education`, `student_groups`),
- marks: `percentage`, or `marks_obtained/marks_total`, of the intermediate-level record (completed or current),
  A-level grades through the IBCC table; unknown marks are allowed,
- the student's live paths (`PossibilityService`, not dismissed) and their `study_field.key`,
- `pai_c/policy/admission_rules.json` (new data file, from the research draft, every rule with sources and
  confidence `official|secondary|uncertain`).

Verdict per field (data-driven, option A: education rules only; budget and city never decide):
| Student | Status |
|---|---|
| group in `groups_open`, marks unknown or ≥ `min_percent` | **open** (marks unknown → "Add your marks to check the N% rule") |
| group in `groups_open`, marks < `min_percent` | **step**: "Needs N%; you have M%" |
| group in a scoped `groups_with_step` | **step**: the rule's step text |
| Matric / O-level | **step**: "Choose <group> in intermediate" (from study_fields group rules) |
| otherwise | **not_open** |
| field with no rule, or a student path with no study field | **unknown**: "PAI cannot check this field yet" |

Route = data, not prose: `now` (current education) → `needs` (marks, subjects, bridge, group choice) → `tests`
(names, pass marks when known) → `degree` (title, years) → sources. Budget and city appear only as information
when the rule has a fee band (none yet).

Computed on read, so it is always current: a Vault or path change shows on the next load. No jobs, no staleness.

## 3. Choosing a route (the decision record)
New table `pai_route_decisions` (migration 118): immutable rows per choice — workspace, field_key, possibility_id
(nullable), verdict and route snapshot, steps (list), steps_done, chosen_at, withdrawn_at. One active row per
workspace. This is the decision record PAI OS reads; `GET /v1/decision-records/current` returns the active row.

API (all `?network=` + workspace auth):
- `GET /v1/roadmap` → `{education_line, counts, fields: [card], chosen: route|null}`
- `POST /v1/roadmap/choose {field_key}` → the new decision; refuses `not_open` and `unknown`.
- `POST /v1/roadmap/steps {index, done}` → ticks a step on the active decision.
- `POST /v1/roadmap/withdraw` → un-chooses.

## 4. What is removed
The old roadmap generation and its UI: `routers/roadmaps.py` (shared `_authorized` moves to a neutral module
first), `pai_c/roadmaps/*`, `plugins/roadmap_builder`, `pai_c/deep/roadmaps.py` and its prompt,
`research/light.py`, the roadmap kinds in `research/gateway.py` (path explain, program search, myth check and
`from_mirror` stay), the `roadmaps.mark_stale` job and its enqueues, the path "Prepare a reviewed roadmap"
route and button, roadmap blocks in chat context (`deep/context.py`, `deep/actions.py` replan, operator
handoff), `checkins` chosen_path (repointed to the route decision), data export (exports route decisions
instead), and frontend `components/roadmaps/*`, `decisions.tsx`, chat roadmap comparison, the old types and
API methods, and their tests. Student requests stay (PAI OS contract) but nothing new comes from roadmap runs.
Mirror `roadmap_lanes` stay: they feed Paths.

Old tables (`pai_roadmaps`, `pai_roadmap_student_state`, `pai_decision_records`) and `pai_possibilities.roadmap_id`
are dropped by migration 119 (founder approved, 26 Oct 2026) after the code stops using them.

## 5. Acceptance
- FSc Pre-Engineering 78% with paths Electrical, Computer, MBBS → Electrical and Computer open (ECAT/NET,
  4 years), MBBS not open.
- Same student at 55% → Electrical is a step "Needs 60%; you have 55%".
- Pre-Medical → Electrical/Civil/Mechanical a step (maths bridge, per-university), MBBS open with MDCAT.
- ICS → Computer Science open, Computer Engineering a step, Mechanical not open.
- Matric Science → step "Choose FSc Pre-Engineering in intermediate".
- No marks → open with the "add your marks" note; no education → the Vault empty state.
- Choosing writes one decision; choosing another withdraws the first; ticking steps persists.
- Nothing in chat, voice or the Mirror creates or changes a roadmap.
- Page works at 375px; Compare table readable on a phone.
