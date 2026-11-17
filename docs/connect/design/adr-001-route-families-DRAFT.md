# ADR-001: Route families (R-81), starting with `pk_intermediate` (DRAFT, revision 2)

**Status:** proposed, awaiting the owner's approval. P3 and P4 start only after it is approved (R-81).

**History:**
- Drafted on 2026-11-15 by a design agent at commit 30d70d2b, and saved by the controller.
- Revision 2 applies corrections A to J from the independent review (`.local-ci/work/P3/adr-001-review.md`).
- After approval it moves to `docs/connect/adr/adr-001-route-families.md`. The repo has no ADRs yet.

**Scope:** phase P3, the Intermediate family (master §12).
- Requirements: R-36, R-38, R-39, R-40, R-49 and R-81; R-13 applies.
- R-58 and invariants 10 and 12 apply throughout.

## 1. Context

### What the master spec asks for
- **R-36:** two families as data, `pk_intermediate` and `pk_bachelor`, each filled in per region, admission body,
  admission system and institution type from the registry. There is never one playbook per institution, and no
  Pakistani names appear in code.
- **R-38:** every stream and every region: college merit, provincial and board rules, domicile, and A-level schools'
  own admission.
- **Streams** (master §1): FSc Pre-Medical, FSc Pre-Engineering, ICS, I.Com, FA/Humanities, General Science and
  A-levels.
- **R-81:** how one family playbook is compiled per region, body and system from the registry, and how a decision maps
  to a family instance.

### How playbooks work today: one playbook per route
- **Selection.** `select_playbook` matches only (origin, destination, level) and returns the newest (version, key)
  (`playbooks/loader.py:63-79`). Two playbooks that share a triple cannot both be live. With equal versions the
  alphabetically last key wins, which would silently pick the wrong region.
- **Route listing.** It is keyed by playbook key (`loader.py:82-91`; `ports/plan_query.py:103-108`).
- **What `PlanService.compile` reads:**
  - route facts, by `playbook.key` (`service.py:94`);
  - programme facts (`service.py:95`);
  - calendar facts, but only for calendar ids written literally in the YAML (`service.py:86-89`;
    `playbooks/models.py:132-138`).
- **Step shape:**
  - Fan-out is `none` or `programme` (`playbooks/models.py:162`; `compiler/compile.py:288`).
  - A step can be gated by one Knowledge fact. If that fact is unconfirmed, the step is provisional and a confirm
    request opens (`playbooks/models.py:40-49`; `compiler/conditions.py:7-14`; `compile.py:292-303`).
  - Step titles are fixed strings (`playbooks/models.py:158`). Only anchor notes have placeholders
    (`playbooks/models.py:52`, `:301-311`).
- **Unknown fields.** `Playbook` forbids them (`playbooks/models.py:23`), so new optional fields leave existing
  playbooks loading as before.
- **Pins and upgrades.** A plan pins (key, version) (`os/models.py:153-160`; `service.py:49-59`). Upgrades find a newer
  version of the same key (`service.py:191-223`). `applies_to` picks a version per intake (`playbooks/models.py:223-237`;
  P2-D25).

### How decisions reach the OS
- `external_ref` is `{journey_id}:{destination_country}:{level}` (`contracts/decision_record_v2.py:51-53`). Self-serve
  plans use `self:{student}:{route_key}:{term}:{year}` (`routes/builder.py:125`). Neither carries a region, a stream or
  a system; only the chosen places (programme refs) do.
- The Counsellor maps (origin, destination, level) to one route key (`pai_c/connect/places.py:134-170`). `places_for`
  asks for that route's programme list (`places.py:172-180`).
- `route_supported` works per triple (`ports/plan_source.py:57-63`; `pai_os_bridge.py:825-833`).
- **Releasing a playbook releases the route.** A playbook file in `PLAYBOOK_DIR` makes `route_supported` true and puts
  the route on the choice screen straight away (`pai_os_bridge.py:825-847`; `places.py:148-162`). An intake nobody
  registered can still be planned (`intakes/store.py:131`).

### What P2 built that a family can use
- **Registry kinds:** regulator, board, admission_body, admission_system, entry_test, institution, campus,
  seat_category, calendar and official_list (`registry/model.py:15-19`).
  - Allowed parents: `model.py:34-41`.
  - `SERVES_A_REGION`: `model.py:26`.
- **Links:** `uses_test`, `has_category`, and `admits` from a system to an institution or campus. A programme is linked
  through `to_kind="programme"` (`registry/store.py:29-33`, `:284-290`; `os/models.py:322-334`). Coverage already uses
  `admits` (`registry/coverage.py:10-14`, `:76`).
- **Programmes.** `os_programmes` has `institution_id`, `campus_id`, `level`, `field`, `family` and `region`
  (`os/models.py:474-480`), and a NOT NULL `route_key` (`os/models.py:465`).
  - The importer creates programmes with `route_key="registry"` (`knowledge/sheets/importer.py:335`, `:498`).
  - It links level, field and region, but never family (`importer.py:502-505`), so `family` is NULL on every imported
    row.
  - Every reader filters on the playbook key (`knowledge/requests.py:107-118`; `knowledge/programmes.py:125-126`).
  - **So today no imported programme is visible to any route.**
- **Calendars:** typed calendars (exam, result, admission) with date fields, as data (`registry/calendars.yaml`).
  Dates are facts of scope `registry` (`registry/calendars.py:70-104`).
- **Fact classes** are data (`knowledge/fact_classes.yaml:8-28`). They include `application_route` ("How to apply",
  not high-stakes), `deadline`, `schedule_date`, `seat_quota` and `eligibility_threshold`. A `fields:` map gives each
  field its class (from `:29`).
- **Intakes.** `os_intakes` is keyed by (region, family, term, year) (`os/models.py:1103-1119`), with a rollover per
  region and family (`intakes/rollover.py:43-56`).
  - `plannable`, `fallback_applies` and `fallback_year` filter only on (tenant, term, year)
    (`intakes/store.py:127-155`).
  - `intakes/terms.yaml` has no `session` term.
- **Allow-lists** exist per region and family, with family codes `intermediate` and `bachelor`.
- **Replan events** are a closed list that lacks the R-39 events (`replan/events.py:11-12`). It is checked in Python
  only (`events.py:31`), with no database check.
- **Document types:** `ssc_certificate.v1` and `hssc_certificate.v1` already exist (`documents/types/`).

### What the walkthroughs show for intermediate
These are the cited lines only.

| Shape (generic) | Where | Lines |
|---|---|---|
| One central form, ranked preferences, rounds | Sindh public colleges | SI-04 one form; SI-06 up to five colleges in order; SI-08 rounds carried forward; SI-14 confirm within 24 h of the merit list; SI-07 normalised to 550; SI-09 stream minimums; SI-10 zone by matric grade |
| One provincial online system; preference rules not read | Punjab (OCAS), KP (HED portal) | PI-03, PI-05-07; KI-02, KI-03/04 quotas (KI-04 local quota), KI-05 board minimums, KI-06 aggregate, KI-07 Hafiz marks, KI-08 deduction, KI-09 age limit |
| Per institution | AJK: the head of institution admits (AI-02, AI-03). GB: each college has its own apply link (GI-04). ICT: per institution under one FDE policy, with FDE setting the merit-list dates (II-01, II-09) | AI-02, AI-03; GI-04; II-01, II-03, II-04, II-05, II-06, II-09 |
| Unknown | Balochistan | LI-03-05 are gaps |

### Gaps
- **A-level schools:** no official list exists in any region (PI-14, SI-21, KI-13, II-12, N-30).
- **Private colleges:** the only list read is BIEK's, for Karachi (SI-18). None was found elsewhere (PI-14, KI-13,
  II-12).
- **ICT:**
  - The FDE Model Colleges page was `not_readable` (Cloudflare 403, II-10), so ICT public places stay `listed`.
  - The FDE 2026 HSSC-I schedule was not read (II-11).
  - Note: the FDE HSSC participating-institutes list was loaded locally in W12 (D-FDE).
- **GB:** merit rules, quotas and the calendar were not found (GI-06).
- **Balochistan:** the board list was not read (LI-02).
- **Punjab:** there is no documents line (PI-13).
- **Dates:** most 2026 admission dates were not read (KI-14, AI-10, II-11, LI-05, SI-15).
- **Intake wording:** PI-08 has BISE Lahore's 11th-class registration for "Academic Session 2026-28". GI-05 shows the
  same wording for SSC-I only, which is not an intermediate intake.

## 2. The decision to make
1. The shape of a family.
2. How region × stream × institution type map to steps.
3. Which data lives in the registry, calendars and systems, and which in the YAML.
4. Versioning and rollover.
5. Stage H.
6. The decision-to-instance mapping.
7. How a family is released without reaching students before its gate.

## 3. Options

### A. One playbook per region (or per region × stream)
**Pro:** simple for the compiler.

**Cons:**
- `select_playbook` cannot choose between playbooks that share (PK, PK, intermediate) (`loader.py:71-79`). Choosing
  would need a contract v3 that carries the region, and even then a plan could not hold places in two regions.
- Many routes per level would appear on the choice screen.
- Registry facts would be copied into YAML, giving two owners (R-01).
- Every rule change bumps one of dozens of versions.
- It comes close to the one-playbook-per-institution pattern R-36 forbids.

### B. One family playbook with per-region blocks in the YAML
**Pro:** keeps one key.

**Cons:**
- Region facts move into YAML, although Knowledge and the review queue should own them (R-23, R-60, P2-D4).
- A variant has to be chosen per place, which is option C done badly.
- A change in one region bumps the version for every region (`service.py:191-205`).
- The YAML grows to the size of the registry.

### C. One family playbook of generic steps, compiled per place from the registry (recommended)
**How it works:**
- Steps are written against generic admission modes (data vocabulary) and generic registry roles: the place's system,
  calendar, seat categories and body.
- At compile time each place resolves to its institution (and from it the region and type) and to the system that
  `admits` it.
- Steps fan out per system or per place, are gated by the system's mode fact, and are dated from the system's
  calendar.

**Pros:**
- No contract change, and a plan can hold places in several regions.
- Each fact keeps one owner, with its trust levels, monitoring and rollover.
- A rule change is a data change that reaches plans as a revision (row 6.10). This is consistent with invariant 10,
  because conditions already add or remove steps by revision. Only a change to the step shape is a new version.
- It reuses the existing Condition provisional/confirm path and the `application_route` class.
- It serves `pk_bachelor` in P4.

**Cons:**
- Compiler work: system fan-out, system anchors, title placeholders, and registry-change revisions.
- Missing data must stay honest: provisional steps marked "not confirmed".
- A region's flow is harder to read in one place. T13 adds a plan preview for that.

### D. Per-region playbooks generated from the registry
- The snapshot goes stale during the season.
- Every regeneration is a new version, which churns pins.
- Option A's selection problem remains.
- The generated file is a second owner of registry data.

## 4. Recommended option: C

| # | Decision |
|---|---|
| D1 | **One playbook per family and level:** `playbooks/pk_intermediate.v1.yaml`, `key: pk_intermediate`, route (PK, PK, intermediate), with a new field `family: intermediate`. That field is the registry and allow-list family code. Code maps a playbook to a family only through this field, never through a name. |
| D2 | **A decision maps to an instance unchanged.** `select_playbook` returns `pk_intermediate`, and `external_ref` is unchanged. The instance is the pinned (key, version) plus the chosen places. Each place resolves at every compile to (region, institution type, admission system, stream) from the registry. There is no contract change: `DecisionRecordV2.level` already allows intermediate, and `ProgrammeListV2` already carries coverage_level, region and not_run_yet. A plan may hold places in several regions. |
| D3 | **Admission modes are data, and steps that depend on them stay provisional until verified.** `registry/admission_modes.yaml` lists the generic modes (`central_ranked`, `central_portal`, `per_institution`). A system's mode is a Knowledge fact `admission_mode` on the `sys:` entity, added to the `fields:` map of `fact_classes.yaml` as class `application_route`. **Its source is the official URL and verbatim quote that the walkthrough line cites,** and it enters only through the P2 import and review lane. This ADR sets no mode. Every mode-gated step stays provisional, shown as "not confirmed", until the mode fact is `verified` (Q9). |
| D4 | **Programmes belong to a family by their columns, not by `route_key`.** One helper, `programmes_of(playbook)`, decides which programmes a playbook sees. With `family` set: the active programmes whose family and level match the playbook. Without it (Germany and the fakes): today's `route_key` match. **Every reader calls the helper:** `adapters/counsellor/intake.py:236` and `:306` (without it, every Counsellor decision is refused as `unknown_programme`); `routes/builder.py:86`; `api/self_serve.py:74`, `:114`, `:123`; `eligibility/notes.py:120`; `replan/apply.py:204`; `ports/plan_query.py:66`; `programme_list_v2.py:36`; `knowledge/requests.py:107`; `knowledge/programmes.py:125`. **Where `family` comes from:** the importer writes the run's `--family` (`importer.py:335`) through `link_programme` (`registry/store.py:308-311`). A row whose official lists name a different family is refused. A backfill applies the same rule to rows already imported; it is a script with a log and an undo, not a migration, because the column exists since os_0027. |
| D5 | **New generic compiler units:** `fan_out: system` (one instance per system, holding its places in rank order); `anchor.of: system \| system_calendar`; `condition.of: system`; and title placeholders `{system}`, `{body}`, `{institution}` filled from registry names. A place with no `admits` link falls back to per-place steps, provisional, with a confirm request for the mode. It is never dropped silently. These paths are reached only through `family` or the new values, so Germany and the fakes compile byte-for-byte as before. |
| D6 | **Streams are programme rows; zone, domicile and residency rules are facts.** Each stream offered is one programme row, with its stream code in `field`. Stream rules (SI-09, II-06) are programme or system facts with an `owner_ref`, and they enter eligibility as data. Zone, domicile and residency rules (SI-10, II-04, KI-04) are also facts with an `owner_ref`. Eligibility reads the student's domicile and place preference from StudentFacts (R-13). If either side has no fact, the rule is not applied and the step stays provisional; it never shows "not eligible" (R-17). The stream list is a data file (Q3). |
| D7 | **What lives where.** *YAML:* generic steps, their order and dependencies, needs and asks, evidence levels, cited constants and pages. *Registry:* bodies, systems, links, calendars, institutions, campuses and programmes. *Knowledge, per intake:* mode, dates, quotas, minimums, zone and domicile rules, formulas, fees and windows. *Never in YAML:* a body or portal name, a date, a quota or a fee. |
| D8 | **Registry changes revise plans.** A change to a link, a mode or a calendar date revises the plans whose places resolve to it, on the row 6.10 path. The resolved system ids are kept in `fact_refs`. |
| D9 | **Intakes are region-aware.** A plan can be planned only when every place's (region, family, term, year) intake is open or current. The fallback is applied per place's region. With no registered intake, behaviour stays as today. |
| D10 | **Versioning.** One version line per family, with `applies_to` per intake. A region's new rule or date is data, not a version. A new step shape, or a new mode handled, is a new version. Pins hold, and plans move only through the upgrade proposal. Rollover runs per (region, intermediate, term, year), and its expected slots include system mode and calendar facts. The term follows Q2. |
| D11 | **Stage H (R-49).** Places come from programme_list_v2 for the family, filtered by R-15, by R-13 domicile and place preference, and by the eligible stream from the matric or O-level group, each with its coverage level. A place that is only `listed` shows "PAI can't run this place yet" (R-35d). The feature sits behind the flag `CONNECT_STAGE_H_FROM_OS`, through an adapter that returns today's `paths/programs.py` shape (master §10). `places_for` passes the student (closes FU-13; `programmes_for` already takes `student_ref`, `pai_os_bridge.py:909`). `places.py`, `paths/programs.py` and `pai_os_bridge.py` are not on the freeze list, but they are under CODEOWNERS, so the Counsellor lead approves them. |
| D12 | **Events (R-39).** The six event types are added to `EVENT_TYPES`; no migration is needed. Detectors read registry and Knowledge facts and the student's step answers. The texts are data and are never sent to chat (R-45). `merit_list.next_round` matters where rounds are cited (SI-08). `test.result_published` serves P4. |
| D13 | **Documents (R-40) are data, with a phase per type** (table below). The existing ssc and hssc types are reused, or versioned as v2 if a field is added. A step needs a type only with a citation that it is required. |
| D14 | **Release flag, off by default.** A family playbook is offered by `routes()`, `supports()`/`route_supported` and `select_playbook` for new plans only while its flag `CONNECT_FAMILY_<FAMILY>` is on (for example `CONNECT_FAMILY_INTERMEDIATE`). The flag is found by one generic lookup on the playbook's family code, so no family name appears in code. With the flag off, routes, support and every Counsellor screen are byte-for-byte as today. A plan already pinned to the family keeps running. The flag is turned on for the P5 pilot, not in P3 (Q8). |

**D13 types:**

| R-40 type | Phase | Citation that a step may need it |
|---|---|---|
| CNIC / B-Form / NADRA Juvenile Card | P3, type and need | SI-11 (SECCAP registration). N-37 covers equivalence applicants only |
| IBCC equivalence certificate | P3, type and need | II-08, AI-04, N-36-N-39. Conditional on a foreign or O/A-level qualification. N-32 and N-34 are the equivalence rules, not a document need |
| SSC mark sheet and certificate | P3; reuse `ssc_certificate.v1` (9th-class mark sheet as a part, SI-05) | SI-05, SI-11 |
| HSSC mark sheets and certificate | P3 type, reusing `hssc_certificate.v1`; needed in P4 | none for intermediate admission |
| O-level / A-level statements | P3 type | none yet |
| Domicile certificate | P3 type | none yet for intermediate |
| Character certificate | P3 type | none yet |
| Migration certificate | P3 type | none yet |
| Fee challan receipt | P3 type | none yet (waits for a cited fee step) |
| Entry-test result card | P4 | N-13 is a bachelor's-level test (ETC) |

A "none yet" type is defined as data, but no step needs it until research cites it.

**Why C.** It is the only option that keeps one owner per fact (R-01, D-03) and keeps the contract and `external_ref`
unchanged. It also handles places in several regions, and it turns rule changes into revisions instead of versions.

**Invariants kept:**
- **R-58 / inv. 12:** code knows only generic concepts. The red-flag test (`tests/os/test_invariants.py:72-89`) is
  unchanged. P3 adds a fake intermediate family on `.test` domains.
- **Inv. 10:** pins hold. Data changes reach plans as revisions; shape changes reach them only by upgrade.
- **R-01:** `family` belongs to `os_programmes`, which OS Knowledge owns. The student's board, domicile and preferences
  come from StudentFacts, never directly from an OS document (master §4).
- **Never inventing data (D-11, §13.2):**
  - No mode, date or rule comes from this ADR or from code.
  - A mode needs a cited official URL and quote.
  - Mode-gated steps stay provisional until verified.
  - Missing data gives provisional steps, a confirm request, and "not confirmed" on screen.
  - A place with no official list shows "PAI can't run this place yet".
  - Balochistan, A-level schools and private colleges outside BIEK Karachi stay that way until research cites them.
- **R-25:** facts pass through the one display function.
- **R-56 and the §10 flags rule:** the new route stays off until its flag is on (D14).

## 5. Consequences

**Good:**
- There is one family file to review.
- Region work becomes data work in the P2 checker lane.
- P4 reuses D3-D9 and D14.
- The Counsellor sees one route per level, and only once the flag is on.

**Costs:**
- About five compiler and schema changes (D4, D5, D8, D9, D14). This is the riskiest code in P3, because the compiler
  is shared. Each change needs a byte-for-byte compile test for Germany and the fakes.
- D4 touches about ten readers through one helper. A missed reader would refuse every family decision, so the review
  checks the full list.
- Imports must carry `admits` links and modes. Without them, places fall back to provisional steps.
- `family` is NULL on every imported row today, so the backfill runs before the family sees any place.
- The label test (R-55) must cover regions inside one route. It reads its word lists from the fake registry and renders
  the real `pk_intermediate` per region.

**Accepted limits:**
- A-level schools and most private colleges stay `listed`.
- ICT public places stay `listed` until the FDE Model Colleges list is collected (II-10).
- Balochistan and GB stay mostly provisional (LI-02-LI-05, GI-06).
- Coverage up to the launch gate is P5 work.

**Observation:** `tests/os/playbooks/calendar/pakistan_inter.v3.yaml:5` says `level: bachelor`, while its v1 and v2 say
`intermediate`. Confirm whether that is intended.

## 6. P3 tasks

**How tasks run:**
- Code tasks: an implementer and an independent reviewer, with fix rounds. The reviewer checks the R-IDs, that nothing
  is hardcoded or invented, and that no frozen file is touched.
- Data tasks: check 1 and an independent check 2.
- Branches are named `pc/p3-t<N>-<name>`.
- Sizes: S up to 2 days, M 3-5 days, L 1-2 weeks.

| # | Task | Kind | Size | R-IDs | Needs |
|---|---|---|---|---|---|
| T0 | The owner approves the ADR; R-81 becomes built: true | Owner | S | R-81 | — |
| T1 | Playbook schema (`family`, `fan_out: system`, `anchor.of`, `condition.of`, placeholders, load checks) and the **D14 release flag**; Germany and the fakes load unchanged | Code | M | R-36 | T0 |
| T2 | Family programme binding (D4): the helper plus every caller; the importer writes `--family` and refuses rows whose lists disagree; backfill script with a log and an undo | Code | M | R-36, R-49 | T0, T1 |
| T3 | Admission-mode vocabulary (D3): `admission_modes.yaml`, the `fact_classes` field, import validation, provisional until verified | Code | S | R-38 | T0 |
| T4 | Compiler: place → system via `admits`; system facts and calendars; fan-out; fallback; zone/domicile/residency rules read from StudentFacts (D6); Germany byte-for-byte | Code | L | R-36, R-38, R-13 | T1, T3 |
| T5 | Registry-change revisions (D8) | Code | M | R-36 | T4 |
| T6 | Region-aware intakes (D9) | Code | M | R-63, R-38 | T4 |
| T7 | Events R-39 (D12) | Code | M | R-39 | T4 |
| T8 | Document types R-40 (D13): types, field-to-fact mapping, fictional fixtures | Code + data | M | R-40 | T0 |
| T9 | Intake term: `session` in `intakes/terms.yaml` | Data, 2 checks | S | R-62 | Q2 |
| T10 | Fake intermediate family: every region code, all modes, a region with no data, every stream, zone and domicile rules; fictional students | Code (test data) | M | R-36, R-38, R-58 | T1-T4 |
| T11 | `pk_intermediate.v1.yaml` plus its pages file; citations only from walkthrough lines | Data, 2 checks | M | R-36, R-38 | T1, T3, T4, T8, T9, T12; Q2 |
| T12 | Region system data: one system per cited region, mode fact (URL plus quote), `admits` links, calendars; Balochistan recorded as a gap | Data, 2 checks | L | R-38, R-33 | T2, T3; W12 |
| T13 | Plan preview per region (admin, read-only) | Code | S | R-38 | T4 |
| T14 | Stage H from the OS (D11): flag, adapter, places_for with the student (FU-13), R-13 filter, replay; Counsellor lead review | Code (Counsellor) | L | R-49, R-15, R-13 | T2, T10; Q3 |
| T15 | Label test per region, red-flag check, flag-off byte-for-byte tests (D14 and the Stage H flag) | Code | S | R-55, R-58 | T10, T11 |
| T16 | Gate: every region × stream; Spike 2; rehearsal; traceability --gate P3; P3 handoff | Code + people | M | all P3 | all; Q6, Q7 |

**Order:**
1. After T0, run T1, T3 and T8 in parallel, and T9 once Q2 is answered.
2. T2 follows T1.
3. T12 starts once T2 and T3 are done. Its research can start earlier.
4. T4 follows, then T5, T6, T7, T10 and T13.
5. T11 waits for T4, T8, T9 and T12.
6. T14 needs T2 and T10. T15 needs T10 and T11.

**Critical paths:**
- Code: T1 → T4 → T10 → T15 → T16.
- Data: T12 → T11.

**R-ID coverage:**

| R-ID | Tasks |
|---|---|
| R-36 | T1, T2, T4, T5, T10, T11 |
| R-38 | T3, T4, T10, T11, T12, T13 |
| R-39 | T7 |
| R-40 | T8 |
| R-49 | T2, T14 |
| R-81 | T0 |
| R-13 (applied) | T4, T14 |

## 7. Gate mapping (master §12, P3 row)

| Gate item | Proved by |
|---|---|
| ADR approved | T0 |
| Fictional students in every region and stream get correct plans | T10 and T16: every region × stream × mode with zone and domicile rules; a region with no data (provisional throughout, never guessed; Q7); a two-region plan. The answer key comes from someone other than the T4 implementer. |
| Spike 2 on the new documents | T8, scored with `doc_scoring`. A billed run only if Q6 allows it (default: none). |
| Rehearsal | T16: a full intermediate cycle with the R-39 events. The D14 flag is on in the rehearsal environment only. |
| Always (R-56-R-59) | Full suites, tach, one Alembic head, flags off byte-for-byte (D14 included), traceability |

Not in P3: turning `CONNECT_FAMILY_INTERMEDIATE` on for students. That is the P5 pilot (Q8).

## 8. Open questions for the owner

1. **Names.** Should the playbook key be `pk_intermediate` and the family code `intermediate`, linked by the `family`
   field? *Default: yes.*
2. **Intermediate intake term.** For "Academic Session 2026-28" (PI-08), use term `session` with the first year, as in
   the import rule (P2 §11.3)? This needs a `session` entry in terms.yaml (T9). *Default: yes.*
3. **Stream codes.** Should `field` use the Counsellor's study-field codes for the streams, so that R-15 works, or
   should P3 add a stream list with a mapping in field_codes.yaml? The Counsellor lead must answer too.
4. **A-levels and private colleges.** There is no official A-level list in any region, and the only private-college
   list is BIEK's for Karachi. *Default:* the gate covers these on fictional data only, and real places stay `listed`
   until research finds a list (P5).
5. **The student's board calendar.** *Default:* read the student's board from StudentFacts. That is the Vault value,
   confirmed from the SSC document through the reconciler; OS documents only propose it (master §4). Match it to a
   registry board through the registry's aliases. Until it matches, the step shows "result expected" with no date,
   plus a provide step. Never guess the board.
6. **Spike 2 cost.** Run it on free or local models only, or set a cap? *Default:* no billed run; local or recorded runs
   only.
7. **The Balochistan gate.** Does a plan that is provisional throughout, and never guessed, count as "correct" for the
   gate's "every region"? *Default:* yes, with LI-02-LI-05 recorded as gaps. The same applies to GB (GI-06).
8. **Release flag.** Should the route stay off in production until the P5 pilot (D14)? *Default:* yes.
9. **Optional: is `admission_mode` high-stakes?** Should it get its own high-stakes class? *Default:* no, because D3
   already keeps mode-gated steps provisional until verified.
