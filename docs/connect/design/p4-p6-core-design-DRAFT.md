# Design: core engineering for P4 (Bachelor's family), P5 (Launch, code part), P6 (Abroad). DRAFT

Saved by the controller on 2026-11-15 from a read-only design agent, at commit 0d86901c. It builds on ADR-001
revision 2 (work/P3/adr-001-route-families-DRAFT.md). Status: owner approval pending. P4's new units need an ADR-001
addendum (P4-T0). All paths are under backend/app/os/ unless stated otherwise.

Every rule value (modes, dates, formulas, choice limits, visibility, tests) comes in as a cited fact through the P2
lanes. The design names no institution rule. Walkthrough line ids (PB-05, SB-10, ...) are used only to show shapes.

## 0. Findings that shape these phases

1. **Gate (b) passes when it checks nothing.** Reading (b) checks only the institutions whose `attrs.first_live` names
   the intake (`coverage/report.py:244-246`). Nothing ever sets `first_live`, so (b) checks zero institutions and
   reports green. P5 must fix this.
2. **"national" is a Pakistani region code used as a global one.** It is `NATIONAL` in `registry/model.py:32`, and
   `knowledge/regions.yaml:16` defines it as a Pakistani region. Code reads it as "serves every region" in:
   - `coverage/report.py:114` and `:221`
   - `sheets/plan.py:110`, `:469-470`, `:544-545`
   - `registry/store.py:171`

   There is no country column. Region uniqueness is checked only within one country (`knowledge/regions.py:36-46`),
   while `known_region` searches all countries (`registry/model.py:63-64`).
3. **The release flag is global, keyed by family code only** (`settings.py:81-84`). So there is no per-student pilot,
   and two countries with a `bachelor` family would be released together.
4. **MeritCheck reads only the programme's own facts** (`merit_check.py:265-271`). A formula owned by a system or body
   (PB-02, SB-04, KB-04) is never found. A part's total comes only from a Vault key pair (`merit_check.py:338-353`;
   `requests/limits.yaml:5-7`), and there is no test-total key (`pai_c/connect/student_facts_keys.yaml:19-21`).
5. **Already built and reused:**
   - date facts carry a time zone (`compiler/compile.py:129-138`, `:355`);
   - Part-I and Part-II marks keys exist (`student_facts_keys.yaml:16`; `requests/limits.yaml:6-7`);
   - MeritCheck uses exactly the keys a formula names (`merit_check.py:343-346`).

## P4: Bachelor's family (`pk_bachelor`)

**Needs beyond P3:**
- **(a) Family, systems, modes, binding and flag:** reused from ADR D1-D5, D7-D10 and D14. P4 adds data only.
- **(b) Entry tests as their own unit:**
  - One test serves many systems (N-14, N-09).
  - A calendar cannot have a test as its parent today (`registry/model.py:40`).
  - The `exam` calendar fields and the `uses_test` link already exist.
- **(c) Conditions on a student fact:** for example, IBCC applies only to O/A-level or foreign students (PB-04, N-34,
  N-36). Today Condition reads Knowledge facts only (`compiler/compile.py:270-275`, `:305-318`).
- **(d) Merit rounds:** PB-06, SI-08. The calendar has a single `merit_list_date`.
- **(e) R-70 share-your-position step,** with rule 13 and no password ever handled.
- **(f) R-73 on the plan side:** the Part-I mark sheet is asked for as soon as the plan is built.
- **(g) MeritCheck through the formula owner (R-75),** with test totals and alternative parts (SB-10).
- **(h) Choice limits and ranked preferences:** PB-05, SI-06.
- **(i) Document types:** test result card and fee challan.
- **(j) Event detectors:** `merit_list.*`, `fee_deposit.due`, `test.result_published`. Agree the scope with P3-T7.
- **(k) Stage H:** reused from P3-T14. P4 adds the stream-to-field facts only.

**Decisions:**

| # | Decision |
|---|---|
| P4-D1 | **The family.** `playbooks/pk_bachelor.v1.yaml`, `key: pk_bachelor`, `family: bachelor`, route (PK, PK, bachelor). ADR D2-D14 apply unchanged. `CONNECT_FAMILY_BACHELOR` stays off until the pilot. The fake `pakistan_bs.v1.yaml` stays. The new units go into an ADR addendum the owner approves. |
| P4-D2 | **Modes.** Reuse `admission_modes.yaml`. A new mode is added only from a cited walkthrough line. |
| P4-D3 | **Tests are links, not modes.** An `entry_test` entity linked by `uses_test`, with its own exam and result calendars; `entry_test` becomes an allowed calendar parent. New units: `fan_out: test` (one step per distinct test), `anchor.of: test_calendar`, and a `{test}` placeholder. The step is met when the Vault holds `test.<code>.score`. `registry/test_codes.yaml` maps registry test ids to Vault codes. A programme's `test_options` gives a "choose your test" step per place. Missing data gives a provisional step with no date. |
| P4-D4 | **`condition.of: student`.** The condition reads a StudentFacts key, with qualification codes as playbook data. A missing value makes the step provisional and opens a provide request. **IBCC equivalence is a prerequisite step with this condition, not a mode.** IBCC is a registry body. If P3-T8 needs this in P3, move it to P3-T4. |
| P4-D5 | **Rounds.** Numbered calendar fields: `merit_list_date_<n>`, `fee_deposit_due_<n>`. The step field `repeat: round`, under `fan_out: system`, gives instances `...@<system>#<n>`. Round n+1 appears after "not on list n" or after an upgrade fact. A round with no date is a provisional "next list expected" step. Instance keys are stable (inv. 10). A fee window is an offset after a fact date, with its length from `fee_window_days` (class deadline), never a constant. Upgrades apply only where the fact `upgrade_rounds` says so. The events are detected from these facts and answers. |
| P4-D6 | **R-70.**<br>(1) The system fact `merit_list_visibility` (class application_route, cited) gates a provide step on the round's list date.<br>(2) Document type `merit_position_screenshot.v1`, at `shown`. Its fields: listed yes/no, list number, position or aggregate, seat category. No credential field. The ask says never share a password.<br>(3) Proposed through FactProposalSink, under the Vault namespace `merit_position.<place-slug>.<field>` (meaning `student_reported`). The Counsellor map changes go in `pai_c/connect/document_facts.yaml` and `app/memory/evidence_policy.json`; the Counsellor lead reviews them.<br>(4) The value drives only that student's claim, fee and upgrade steps.<br>(5) Rule 13: Knowledge refuses the namespace. `closing_merit*` comes only from the import, review or monitoring lanes on allow-listed domains. Nightly check in `consistency/facts.py`.<br>(6) Tests: no password, PIN or credential field, ask or form anywhere; the gateway refuses URLs with user-info; no OS code submits a form to a portal. |
| P4-D7 | **R-73.** The step field `needs_from: merit_formula` adds a need for each marks key the place's formula names, at the playbook's evidence level (`shown` for Part-I). It is due when the plan is built and cites the formula fact. The Part-I mark sheet type proposes `education.intermediate.part1.*`. One request per fact. An unconfirmed formula still asks, and the step is marked provisional. |
| P4-D8 | **MeritCheck through the owner.** Use the programme's own formula, else the admitting system's (`KnowledgePort.registry_facts`, `knowledge/port.py:76`, plus P3-T4 resolution); `Formula.owner_ref` names the owner (R-75). A part may carry `test:`, in which case its total is that test's verified `max_score` fact. A part may carry `alternatives:` in cited order, and the first one held is used (`marks_used`). `merit_check.v1` is unchanged. Extend the shape check in `knowledge/merit.py:103-130`. |
| P4-D9 | **Choice limits.** The system fact `max_choices` plus the place rank. Places over the limit raise a proposal, never a silent drop. "Must rank all" makes the application step a `choose` step. |
| P4-D10 | **Result card.** `entry_test_result.v1`, with templated keys `test.{test_code}.score`; `test_codes.yaml` maps the codes. The fee challan is needed only by a cited fee step. |

**Tasks** (size, R-IDs, dependencies; "P3-" means a P3 task):

| # | Task | Kind | Size | R-IDs | Needs |
|---|---|---|---|---|---|
| P4-T0 | ADR-001 addendum for D3-D8; owner approval | Owner | S | R-81 | P3-T0 |
| P4-T1 | Test unit (D3) | Code | L | R-37, R-33 | P3-T1, P3-T4 |
| P4-T2 | `condition.of: student` (D4) | Code | M | R-37, R-13, R-17 | P3-T1 |
| P4-T3 | Rounds (D5), with the round and fee detectors | Code | L | R-37, R-39 | P3-T4, P3-T7 |
| P4-T4 | R-70 (D6) | Code + Counsellor | M | R-70 | P4-T3, P3-T8 |
| P4-T5 | MeritCheck through the owner (D8) | Code | M | R-31, R-48, R-73, R-75 | P3-T2 |
| P4-T6 | R-73 plan side (D7) | Code | M | R-73, R-16, R-18 | P4-T5, P3-T4, P3-T8 |
| P4-T7 | Result card, fee challan, `test.result_published` (D10) | Code + data | M | R-40, R-39 | P4-T1, P3-T7, P3-T8 |
| P4-T8 | Choice limit and must-rank-all (D9) | Code | S | R-37 | P3-T4 |
| P4-T9 | Fake bachelor family covering every shape | Code (test data) | M | R-36, R-37, R-58, R-70, R-73 | P4-T1-T8 |
| P4-T10 | Bachelor's region system data | Data, 2 checks | L | R-37, R-33 | P3-T2, P3-T3, P4-T1 |
| P4-T11 | `pk_bachelor.v1.yaml` plus pages | Data, 2 checks | M | R-36, R-37 | P4-T1-T8, P4-T10 |
| P4-T12 | Stage H bachelor's filters | Code (Counsellor) | S | R-49 | P3-T14 |
| P4-T13 | Label test, red-flag test, flag-off byte-for-byte | Code | S | R-55, R-58 | P4-T9, P4-T11 |
| P4-T14 | Gate, rehearsal, traceability --gate P4, handoff | Code + people | M | all P4 | all |

**P4 gate:**
- Fictional students across every system: P4-T9 and T14.
- The login-only merit list with no password: P4-T4 and T9.
- The live-run MBBS/BDS student: P4-T14. This needs real data, and money or the owner if a live graded run is used (a
  replay is the free proof).
- Rehearsal.
- R-56 to R-59.

## P5: Launch (code part; the legal review is excluded)

**Needs:**
- (a) A launch view across family × region (today: one intake at a time, `api/coverage.py:35-40`).
- (b) First-live marking, so that (b) stops passing vacuously.
- (c) A pilot cohort per family; about eight D14 call sites.
- (d) A release flag guarded against a red gate.
- (e) Measuring pilot students who reach submission.
- (f) The pilot consent text, which is owner/legal work (the mechanism already exists in `consent/pilot.v1.md` and
  `terms.py`).

**Decisions:**

| # | Decision |
|---|---|
| P5-D1 | **Launch matrix as a read.** For each (region, family) on a given (term, year), run `coverage.report.build`. A cell is green only if the report is green AND the intake is `current`. Exposed as an admin API, a dashboard table and a CLI. |
| P5-D2 | **`coverage/launch.yaml`.** The owner's D-17 first-live intakes per family and region. Every in-family institution of that region is first-live by default. An exception needs a cited override through the review lane. A new item `no_first_live` covers the case where a declared intake has zero first-live institutions. |
| P5-D3 | **Pilot release.** The flag can be `pilot` as well as on or off. A cohort table `os_pilot_members` (tenant, family, student_ref, added_by, added_at, removed_at) needs an Alembic migration. `released_for(settings, student_ref)` is used at every D14 call site. The Counsellor callers (`places.py:172-180`, `pai_os_bridge.py:825-847`) pass the workspace; the Counsellor lead reviews this. Pilot consent is required. Pinned plans keep running. |
| P5-D4 | **Region-level launch.** For a family that is on, a place whose region cell is not green gets the R-35(d) label and is not plannable as current. Last year's values are still shown, labelled (R-63). A new consistency rule opens a case when the family is on while a first-live cell is red. |
| P5-D5 | **Submission milestone.** The step field `milestone: submitted` (data), plus a pilot report counting the plans that reach it. |

**Tasks:**

| # | Task | Kind | Size | R-IDs | Needs |
|---|---|---|---|---|---|
| P5-T1 | Launch matrix (D1) | Code | M | R-35, R-66 | none (P3-T6 for per-region plannability) |
| P5-T2 | `launch.yaml`, first-live default, `no_first_live` (D2) | Code | S | R-35(b) | none |
| P5-T3 | Pilot flag, cohort, `released_for` (D3) | Code + Counsellor | M | R-56, R-35 | P3-T1 |
| P5-T4 | Region launch label and release-guard rule (D4) | Code | M | R-35(d), R-66 | P5-T1, P3-T6, P3-T14 |
| P5-T5 | Milestone and pilot report (D5) | Code | S | R-56 | P3-T1 |
| P5-T6 | `launch.yaml` values | Owner data | S | R-35 | P5-T2 |
| P5-T7 | Coverage up to the gate | Data, 2 checks | ongoing | R-35 | checkers |

**P5 gate:**
- R-35 read from the dashboard: needs real data and the owner.
- The legal review: owner.
- Pilot students reach submission: needs real students and the owner's terms.
- A live graded run: needs money and the owner.

## P6: Abroad (R-77)

**Code that must become generic:**
- (a) Region codes unique across countries, with a per-country nationwide region instead of the constant `national`.
- (b) Families bound to one country, with `programmes_of` also filtering on the destination country's regions.
- (c) Country-level facts (visa, funds, language). These are route facts, but the coverage report never reads route
  facts (`coverage/report.py:130-143`).
- (d) A central application service as a mode. It is built from existing units: `fan_out: system`,
  `fan_out: programme`, P4-D9, and the `admission_result` choose step.
- (e) Document types are data. Test score reports reuse P4-D10.
- (f) No time-zone code is needed. Currencies are units in data, and terms are data.
- (g) Fictional test countries, plus red-flag terms for the UK and US (`tests/os/test_invariants.py:15-19`).

**Decisions:**

| # | Decision |
|---|---|
| P6-D1 | **Country blocks in `regions.yaml`.** Region codes are unique across countries, checked at load. Each country has one `nationwide: true` region. Helpers `country_of(region)` and `nationwide_of(country)` replace `NATIONAL` at the six call sites. Pakistan's `national` stays, so no data migration is needed. |
| P6-D2 | **One family code means one key, one destination and one level,** checked at load. Abroad codes are country-qualified data (for example `<cc>_bachelor`). `programmes_of` also requires the destination's regions. |
| P6-D3 | **New abroad routes are family playbooks, each with a per-intake gate.** Germany master stays a route playbook. Making it a family later is the owner's choice, through a new version. |
| P6-D4 | **Country-level facts are the family playbook's route facts.** The coverage report adds them to readings (b) and (c). This covers PK families too. |
| P6-D5 | **No mode in code.** A central service is an `admission_system` with a cited mode fact. |
| P6-D6 | **Documents per country are data.** New fact-proposing types get an authority entry in `document_facts.yaml` (Counsellor review). |
| P6-D7 | **Tests use the fictional countries XA and XB,** with `.test` domains: one with regions, one nationwide only, each with a central service. |
| P6-D8 | **No new Counsellor chat behaviour** (R-77, R-45). |

**Tasks:**

| # | Task | Kind | Size | R-IDs | Needs |
|---|---|---|---|---|---|
| P6-T1 | Multi-country regions (D1) | Code | M | R-76, R-77, R-58 | none |
| P6-T2 | Family-country binding (D2) | Code | S | R-77, R-36 | P3-T1, P3-T2 |
| P6-T3 | Route facts in the gate (D4) | Code | S | R-35, R-77 | none |
| P6-T4 | Two fictional countries (every unit, central service, choice limit, offer reply, visa route facts, labels), plus red-flag terms | Code (test data) | M | R-77, R-55, R-58 | P6-T1-T3, P3-T4, P4-T8 |
| P6-T5 | Per country and level, five times: walkthrough, allow-list, lists, registry, system facts, playbook, documents, terms | Data, 2 checks | L each | R-77, R-23-R-36, R-60-R-76 | P6-T1, P6-T2 |
| P6-T6 | Gate per country and level | Code + people | M each | R-77 | P6-T4, P6-T5, P5-T1 |

**P6 gate:**
- Fictional plans: P6-T4.
- Walkthroughs, registry and launch gate: need real data, checkers and the owner.
- Spikes: money.

## Owner questions (each with a default)

1. **Shared compiler units.** *Default:* reached only through `family` or a new field value, with byte-for-byte tests,
   in one ADR addendum (P4-T0).
2. **A-level equivalence marks.** *Default:* their own Vault keys, used only when cited as an `alternative`.
3. **R-70 `student_reported`.** *Default:* a key namespace plus a new authority; the Counsellor lead reviews it.
4. **Region-level launch (P5-D4).** *Default:* region by region.
5. **Who sets the `launch.yaml` values.** *Default:* the owner. Until then, (b) shows red.
6. **Germany master as a family?** *Default:* no.
