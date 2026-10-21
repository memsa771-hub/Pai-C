# PAI OS Slice 4: Self-serve start and eligibility (design)

Date: 2026-10-21. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§3 rule-based workers, §6 Slice 4,
invariant 12). Builds on Slices 0–3 on `pai-os`.

**Goal.** A student starts their own plan without the Counsellor or an admin. They pick a route, an intake and up to
10 ranked programmes. Every programme shows an eligibility card: the student's grade converted the route's way,
their language and test proof against the programme's requirements, with sources. The card **warns and never
blocks**, suggests eligible swaps, and updates by itself as the student's documents are confirmed.

**Done when (parent §6, plus the owners' scope of 2026-10-21):**
- A test student starts a plan alone, with no admin call and no Counsellor.
- Their eligibility is correct before and after they upload and confirm a transcript and IELTS form.
- They swap a programme, and the plan is revised by the kernel.
- They request a programme not on the list, and it appears, for any student, once research has found facts.
- **The same code serves every route:** the eligibility tests pass on Germany master's and on the two fake routes
  (Pakistan → Ireland master's, Pakistan → Pakistan BS) with different methods. The country-terms check covers the
  new code.

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| S4-D1 | Scope | Slice 4 is the parent's "self-serve start" (the route builder) **plus a per-programme eligibility check**. The grade converter was assigned to Slice 3 by S1-D1, but Slice 3 never built it; it moves here, the first slice that uses it. The **funds calculator stays in Slice 6** with the visa file. |
| S4-D2 | Route-neutral by construction (invariant 12) | Python knows only **generic check kinds** (`grade`, `language`, `test`) and **generic grade methods** (`linear_scale`, `threshold`, `weighted_aggregate`). Each route's playbook says which checks run and how, with its own numbers and its own research facts. A plan is evaluated with **the playbook it is pinned to**, so two students on two routes get their own rules. A new route is config. A genuinely new *kind* of formula is one new generic method, written once and usable by any route. |
| S4-D3 | When eligibility is computed | **On read** (approach A), by a pure function from the programme's facts, the student's profile values and the route's rules. Nothing is stored, so nothing goes stale. |
| S4-D4 | Order of the journey | **Start first, eligibility fills in.** The student can start without documents. A check without its input says which document it needs. The plan's own upload tasks (Slice 3) ask for them, and the card updates when values are confirmed. |
| S4-D5 | Out-of-reach programmes | **Warn, never block, and suggest swaps.** A `likely_below` line shows the numbers and sources. The card offers up to 3 eligible programmes from the registry. A swap happens only with the student's OK, as a kernel revision. Parent rule "a swapped programme has confirmed facts" is relaxed to **has facts**: unconfirmed facts are shown with their ⚠ label (owners, 2026-10-21). |
| S4-D6 | Minimum passing grade | A grade method that needs the student's institution's minimum passing grade starts from a **provisional default** per grade scale (route config). It is labelled on the card: "Estimated with a typical minimum passing grade; upload your university's minimum-passing-grade letter for an accurate result." When the institution's real rule is confirmed (a new document type `min_passing_grade_letter`, added by config only), the estimate recalculates and loses the label. |
| S4-D7 | Change notes | The two existing hooks re-evaluate: Slice 2's `after_fact_change` (a fact changed) and Slice 3's confirm (the student confirmed a value). When a programme's verdict changes for a student with it in a plan, **one inbox note** is written, idempotent per (student, programme, new verdict). |
| S4-D8 | Which programmes | The registry for the route (the researched programmes), plus **"request a programme"**. A request adds a registry row with status `requested` and enqueues research **once**. When facts exist, the programme appears for **every** student, with ✓/⚠ labels; it needs no full verification first. A researched programme is **never researched again for another student**: it is shared like the seeded 30, and only the freshness sweeper re-checks it (owners, 2026-10-21). |
| S4-D9 | Starting a plan | `routes/builder.py` builds a `RouteContract` (`source: self_serve`; `student_ref` from the host sign-in; `external_ref` = `self:<student>:<route>:<intake>`) and calls `PlanService.start_plan`. Starting twice returns the existing plan (the kernel's dedupe). The playbook's `choose_programmes` task is completed by the builder. |
| S4-D10 | Swaps | `POST /plans/{id}/swap {out, in}` rewrites the stored contract's programme list (same rank) and calls `PlanService.recompile` (a kernel revision). Started and protected tasks keep their version, as in every revision. **At most 3 swaps per plan per day**, enforced by the builder (the kernel has no revision limit yet; the parent's Supervisor limit comes in Slice 7). |
| S4-D11 | Spend | Eligibility costs nothing (no model). Requests cost one research run each (Slice 2, about $0.10), within the research monthly cap. **At most 3 requests per student per day.** |

## 2. Components (`app/os/`)

| Unit | Responsibility | Interface |
|---|---|---|
| `eligibility/rules.py` | The playbook's `eligibility:` block as a model, validated at load: checks, methods, the facts they read, grade scales and provisional defaults. | `EligibilityRules`, `load` via the playbook loader |
| `eligibility/methods.py` | Generic grade methods. `linear_scale` (map a grade from the student's scale to a target scale by best grade and minimum pass, optionally inverted; the German modified Bavarian formula is this with target best 1.0, worst pass 4.0). `threshold` (compare on one scale, e.g. a percentage). `weighted_aggregate` (a weighted sum of named profile values, e.g. a merit aggregate). | `convert(method, inputs) -> Estimate(value, provisional, inputs_used)` |
| `eligibility/evaluate.py` | **Pure.** One card per programme: a line per configured check with status `likely_meets` / `likely_below` / `needs_input` / `unknown`, its numbers, the facts' sources and statuses, and `provisional`. The verdict is the worst line. | `evaluate(rules, facts, profile) -> Card` |
| `eligibility/swaps.py` | Up to 3 programmes on the same route and intake, not already chosen, that are `likely_meets` on the failing line, ranked by how many of their facts are confirmed. | `suggest(rules, card, candidates, profile) -> list[Suggestion]` |
| `eligibility/notes.py` | Re-evaluate before and after a fact change or a confirm, and write one inbox note per changed verdict (idempotent key). | `on_fact_change(...)`, `on_profile_change(...)` |
| `routes/builder.py` | Choices → `RouteContract` → `start_plan`; swaps → contract change → `recompile`. | `start(student, route, intake, choices)`, `swap(student, plan_id, out, in_)` |
| `knowledge/requests.py` | Validate, dedupe and store a programme request; enqueue its research once; enforce the daily cap. | `request(student, route, university, name, url) -> Programme` |
| `documents/types/min_passing_grade_letter.v1.yaml` | New document type by config: the institution's grade scale, its minimum passing grade, and the issuing institution. | Slice 3 pipeline, unchanged |
| Route config | `eligibility:` blocks in `playbooks/germany_master.v1.yaml` and in the two fake routes' playbooks (`tests/os/playbooks/`). | data |

Example (Germany master's, config only):
```yaml
eligibility:
  grade: {method: linear_scale, target: {best: 1.0, worst_pass: 4.0}, requirement: grade_requirement.german_max,
          or_threshold: grade_requirement.percent_min}
  language:
    - {language: english, requirement: english_requirement}
    - {language: german, requirement: german_requirement}
  test: {requirement: admission_test}
  grade_scales:
    cgpa_4: {best: 4.0, provisional_min_pass: 2.0, profile: [cgpa, cgpa_scale]}
    percent: {best: 100, provisional_min_pass: 33, profile: [percentage]}
```

## 3. Tables (Alembic `os` branch, `os_0005`; every table has `tenant_id`)

- `os_programmes.status` also allows **`requested`**. A requested programme shows to students once it has facts.
- **`os_programme_requests`**: who asked, when, the route, the URL given, and the resulting programme. Used for the
  daily cap and for audit; one programme can have many requests.
- **`os_eligibility_notes`**: (student, programme, verdict, at). Only the idempotency key for change notes; the
  note itself is an inbox item.
- No eligibility results are stored (S4-D3).

## 4. API (under `/v1/os`; student calls use the host's sign-in, writes need write access)

| Method and path | Purpose |
|---|---|
| `GET /routes` | Routes the playbooks offer (key, origin, destination, level, intakes) |
| `GET /routes/{route}/programmes?intake=` | Every visible programme on the route with the student's card and its research state (`researched` / `being researched`) |
| `GET /eligibility/{programme_ref}` | One card in full, with swap suggestions when its verdict is not `likely_meets` |
| `POST /plans/self` (`{route, intake, choices: [{programme_ref, rank}]}`) | Start the student's plan. `201` with the plan, or `200` with the existing one. `422` for more than 10 programmes, an unknown route or a programme on another route. |
| `POST /plans/{id}/swap` (`{out, in}`) | Swap one programme (student's own plan only). `409` with the reason if the kernel refuses (a protected task) or the daily swap limit is reached. |
| `POST /programmes/requests` (`{route, university, name, url}`) | Request a programme. `202` with the programme (new or existing). `429` over the daily cap. |

## 5. Student screens (mobile-first, 360 px)

- **Start:** one page in 3 steps.
  1. Route and intake.
  2. Programme list: search; each row shows the programme, the university and a chip (`likely meets` /
     `check this` / `needs your documents` / `being researched`); tapping it opens the card.
  3. "Your choices": ranked, up to 10, reorderable, then **Start my plan**.

  A "Can't find it? Request a programme" link opens a short form.
- **Eligibility card:**
  - a line per check, with the numbers ("Estimated grade 2.3; needs 2.5 or better");
  - the *provisional* tag and its sentence while a default is in use;
  - each fact's source link with ✓/⚠;
  - the footer "An estimate, not a decision: the university decides."
- **Change note (inbox):** the new verdict and why, up to 3 suggestions, and **Swap**, which asks for the
  student's OK first.
- **My programmes** (on the plan page): the chosen list with chips, and **Swap** per row (removing without a
  swap is Q3).

## 6. Error handling

- A missing input gives `needs_input`, naming the document. A missing fact gives `unknown` ("being researched" or
  "not stated by the university"). Nothing is guessed.
- Confirmed values beat provisional defaults. A value with an open Slice 3 finding gives `needs_input` ("resolve
  the mismatch in Documents").
- A route's rules that point at a fact or profile field that doesn't exist fail **at load**, naming the playbook
  and the field (as playbooks and document types already do).
- **Swaps:** the new programme must be on the same route and have facts; the kernel refuses a protected task,
  the builder refuses a 4th swap in a day, and the reason is shown.
- **Requests:**
  - https URL only. The URL's domain becomes the programme's official domain. The request is labelled
    "requested by a student" until an admin reviews it.
  - Duplicates (same URL, or same university and name) return the existing programme.
  - If research finds nothing, the programme stays `requested`, shows "could not be researched yet", and appears
    in the admin's open-facts view.

## 7. Invariants touched

- **4** (agents propose, students confirm): swaps need the student's OK.
- **12** (nothing country-specific in code): methods and checks are generic, and every number and fact name is
  route config. The country-terms check covers `app/os/eligibility/` and `app/os/routes/`.
- **Kernel as sole writer:** plans start and change only through `PlanService` → kernel.

## 8. Testing (TDD; `tach check`, the heads check and `pytest tests/os` before every push)

1. `methods`: table tests per method, including boundaries and the inverted scale. The German example checks that
   `linear_scale` gives the modified Bavarian result.
2. `evaluate`:
   - every status;
   - provisional default → confirmed letter value;
   - missing input versus missing fact;
   - an open finding;
   - worst-line verdict.
3. **Route-neutrality:** the same `evaluate` tests run on Germany master's, Ireland master's (`threshold`) and
   Pakistan BS (`weighted_aggregate` + test). A rules block pointing at an unknown fact fails at load.
4. `swaps`: same route only, not already chosen, eligible on the failing line, ranked by confirmed facts.
5. `notes`: a confirm that changes a verdict writes exactly one note; a replay writes none; a fact change notifies
   every affected student.
6. Builder and API:
   - start; start twice;
   - 11 programmes; an unknown route; a programme on another route;
   - swap → kernel revision; a protected task refused; the 4th swap in a day refused;
   - a student sees only their own plans.
7. Requests:
   - dedupe and the daily cap;
   - research enqueued once;
   - visible to a second student with no new research;
   - stays `requested` when research finds nothing.
8. Screens (Vitest): the chips, the card lines, the provisional tag, swap confirmation, the request form, 360 px.
9. **Slice gate test:** the "done when" journey end to end, with a faked research run and the fake routes
   unchanged.

## 9. Done when (the slice gate)

- §8 is green in CI (`os` and `legacy`).
- The slice gate test (§8 test 9) passes.
- No merge into `dev` at the slice gate: `pai-os` merges into `dev` once, at the end (owners).

## 10. Build order (one branch and PR per task, off `pai-os`)

1. Eligibility rules model and the playbook `eligibility:` blocks (Germany and the two fake routes).
2. Grade methods.
3. `evaluate` and the route-neutrality tests.
4. The `min_passing_grade_letter` document type (config) and its use in `evaluate`.
5. Tables `os_0005`, and programme requests with research once.
6. Swap suggestions.
7. Change notes from the two hooks.
8. Builder and swap through `PlanService`.
9. API.
10. Screens (the shared file `frontend/lib/api.ts` needs a Counsellor reviewer).
11. Slice gate test.

## 11. Open questions for the owners

| # | Question | Proposal |
|---|---|---|
| Q1 | Who reviews student-requested programmes, and how fast? | An admin sees them in the open-facts view; they are usable before review, labelled "requested by a student" |
| Q2 | Provisional minimum-pass defaults per grade scale | CGPA 4.0 → 2.0, percentage → 33; the developers check them against the route's sources in Task 1 |
| Q3 | Should a student be able to remove a programme without swapping? | Yes, while it has no started task; it is a kernel revision like a swap |
