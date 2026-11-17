# Review of ADR-001 (route families) DRAFT

Reviewer: independent agent, 2026-11-15. Read-only review against the code at the working tree, the master spec
(R-36, R-38, R-39, R-40, R-49, R-81, §4, §10, §12), the P2 spec, `backend/app/os/CLAUDE.md` and the walkthroughs.

## Verdict

**Needs changes before it goes to the owner.** The analysis is sound, and option C is the right choice. The code
citations are accurate. But there are two design gaps that would cause real harm if built as written: no release gate
for the new route, and an incomplete D4 caller list. Domicile and zone rules, which R-38 names, are missing. Some
walkthrough citations are wrong, and the task dependencies need fixing. All of these are small text fixes. None of
them changes the recommendation.

## 1. Citations (25 checked)

All of these are correct:
- loader.py:63-79 and 82-91
- ports/plan_query.py:103-108
- service.py:86-89, 94, 95 and 191-223
- playbooks/models.py:132-138 (`Expected.calendar`) and 162 (`fan_out`)
- compile.py:288 and 292-303
- contracts/decision_record_v2.py:51-53
- routes/builder.py:125
- pai_c/connect/places.py:134-180
- registry/model.py:15-41
- registry/store.py:29-33 (`admits` to a programme goes through `to_kind="programme"`, store.py:284-290)
- sheets/importer.py:335 and 498
- knowledge/requests.py:107-118
- knowledge/programmes.py:125-126
- os/models.py:1103-1119
- intakes/store.py:127-155
- replan/events.py:11-12
- tests/os/playbooks/calendar/pakistan_inter.v3.yaml:5 (it says `level: bachelor`; v1 and v2 say `intermediate`)

**No citation is wrong. One is ambiguous.** "models.py" refers to two different files: `playbooks/models.py` (132-138
and 162) and `app/os/models.py` (1103-1119).

## 2. Key findings

1. **"Today no imported programme is visible to any route": true.**
   - The importer creates programmes with `route_key="registry"` (importer.py:335, 498), status `active` by default
     (programmes.py:33).
   - Every reader filters on the playbook key: visible_programmes (requests.py:115) and ProgrammeStore.active
     (programmes.py:126).
   - No playbook is keyed `registry`.
   - Also, the importer never writes `family`: `place` at importer.py:502-505 holds only level, field and region. So
     the `family` column is NULL on every imported row today. D4's backfill is therefore needed for every row, not just
     some.
2. **"plannable/fallback ignore region and family": true.** `_states`, `plannable`, `fallback_applies` and
   `fallback_year` filter only on (tenant, term, year) (intakes/store.py:127-155).
3. **"select_playbook cannot choose between per-region playbooks sharing a triple": true.**
   - The match is on (origin, destination, level) only, and then `max(version, key)` picks one (loader.py:71-79).
   - Two per-region playbooks of the same version would resolve to the alphabetically last key. That silently picks
     the wrong region.

## 3. Option C

- **R-01 is kept.** Mode, dates and quotas stay in Knowledge, and bodies, systems and links stay in the registry. The
  `family` column belongs to os_programmes, which OS Knowledge owns, so it is not a copy.
- **Invariants 10 and 12 and R-58 are kept.** Mode codes and title placeholders are data, and the red-flag scope is
  `*.py` only. Today a fact-driven condition already adds or removes steps through a revision (compile.py:292-303).
  So a mode change reaching a pinned plan as a revision is consistent with invariant 10.
- **Option C is feasible against the compiler as it is.**
  - `Playbook` is `extra="forbid"` (playbooks/models.py:23). New optional fields therefore leave Germany and the fakes
    loading unchanged.
  - Pins load the playbook from the file by (key, version) (service.py:49-59). No serialised playbook or hash changes.
  - The Germany byte-for-byte guarantee holds if every new path is reached only through `family` or the new
    `fan_out`, `anchor.of` and `condition.of` values.
- **Frozen files are not a blocker.** `pai_c/connect/places.py`, `pai_c/paths/programs.py` and `pai_os_bridge.py` are
  not on the master §10 freeze list. They are under CODEOWNERS, so the Counsellor lead must approve them, and the draft
  already says this. No freeze-exception label is needed.
- **No contract change is needed.** `ProgrammeListV2` already carries `coverage_level`, `region` and `not_run_yet`.
  `pai_os_bridge.programmes_for` already takes `student_ref` (pai_os_bridge.py:909). `DecisionRecordV2.level` already
  allows `intermediate`.
- **No migration is needed.**
  - `os_programmes.family` already exists (models.py:479, os_0027), so the D4 backfill is a data change.
  - It should be a script with a log and an undo, like the importer's undo. An Alembic migration cannot read
    list-family data per tenant, so a migration is the wrong tool.
  - The R-39 event types have no database check (`EVENT_TYPES` is checked only in Python, events.py:31), so they need
    no migration either.
- **Hidden blockers found.** These are A and B in §5.

## 4. Data claims checked against docs/research/walkthroughs/

Correct as cited:
- SI-04, SI-06, SI-07, SI-08, SI-09, SI-10, SI-11, SI-14, SI-18, SI-21
- PI-03, PI-05, PI-06, PI-07, PI-08, PI-13, PI-14
- KI-02 to KI-09, KI-13
- AI-02, AI-03, AI-04
- GI-04
- II-01, II-03, II-05, II-06, II-08, II-09, II-12
- LI-03 to LI-05
- N-30, N-36, N-37

Wrong or over-stated:
- **GI-05** is "Registration Notification of **SSC-I** for the Session 2026-2028". That is 9th-class (matric)
  registration, not an intermediate intake. It cannot support "the intake is worded as a session" for intermediate.
- **N-13** is ETC (HEC test) registration. It is a bachelor's-level test, not intermediate admission. The intermediate
  citation for CNIC/B-Form is SI-11. N-37 applies only to equivalence applicants.
- **N-40 and N-41** are about IBCC *attestation*, and N-41 is about HSSC attestation. Neither is about equivalence.
  "IBCC equivalence (II-08, AI-04, N-36-N-41)" over-cites.
- **N-32** is the rule for when O levels count as SSC (eight subjects, minimum grade E). It does not say an "O-level
  statement" document is required. No line cites that document.
- **SI-18** is BIEK private colleges in Karachi only. "Private colleges are listed only by BIEK" reads as if it were
  national.
- **Gaps that are true but not listed:**
  - II-10: the FDE list of model colleges is `not_readable` (Cloudflare 403), so ICT public places stay `listed`.
  - II-11: the FDE 2026 schedule was not read.
  - GI-06: GB merit rules, quotas and calendar were not found.
  - LI-02: the Balochistan board list was not read.

No institution, date or rule is invented in the draft.

## 5. Required corrections (each with the exact fix)

**A. A release gate for the new route (missing).**
- Problem: putting `pk_intermediate.v1.yaml` in `app/os/playbooks/` (PLAYBOOK_DIR) makes
  `route_supported(PK, PK, intermediate)` true, and makes `list_routes` offer PK intermediate on the Counsellor choice
  screen at once (pai_os_bridge.py:825-847, places.py:148-162). An intake nobody registered is plannable
  (intakes/store.py:131). So production students would get OS plans before the P3 gate and before the P5 pilot. That
  breaks R-56 and the §10 flags rule.
- Fix: add **D14**: "A family playbook is offered (routes(), supports(), select_playbook for intake) only while the
  flag `CONNECT_FAMILY_<FAMILY>` is on (default off). With it off, routes, support and every Counsellor screen are
  byte-for-byte as today."
- Add it to T1. Extend T14's flag-off test to cover it. Add "flag turned on for the pilot" to P5, not P3.

**B. The D4 caller list is incomplete.**
- Problem: `ProgrammeStore.active(route_key)` and `visible_programmes(route_key)` take a key, not a playbook.
- Fix: replace "in visible_programmes, ProgrammeStore.active and both programme lists" with "in every reader of the
  route's programmes, through one helper `programmes_of(playbook)`:
  - adapters/counsellor/intake.py:236 and :306 (otherwise every decision is refused as `unknown_programme`);
  - routes/builder.py:86;
  - api/self_serve.py:74, :114 and :123;
  - eligibility/notes.py:120;
  - replan/apply.py:204;
  - ports/plan_query.py:66 (list v1, used by places_for);
  - programme_list_v2.py:36."
- T2 stays M.

**C. Where D4 gets `family`.**
- Problem: "the importer writes `family` from the row's lists" is ambiguous when an institution sits on both an
  intermediate list and a bachelor list.
- Fix: "the importer writes the run's `--family` (run_import already takes it, importer.py:335) and refuses a row whose
  lists name a different family. The backfill uses the same rule. It is a script with a log and an undo, not an Alembic
  migration (the column exists, os_0027)."

**D. Domicile, zone and residency rules (R-38 names domicile).**
- Fix: extend D6. "Zone, domicile and residency rules (SI-10, II-04, KI-04 local quota) are system or programme facts
  with an owner_ref. Eligibility reads the student's domicile and place preference from StudentFacts (R-13). With no
  fact, the rule is not applied and the step stays provisional."
- Add R-13 to T4 or T13.

**E. Fix the walkthrough citations.**
- §1 Gaps: change "(PI-08, GI-05)" to "(PI-08: BISE Lahore 11th-class registration, 'Academic Session 2026-28'; GI-05
  shows the same wording for SSC-I only)".
- Change "Private colleges are listed only by BIEK (SI-18)" to "The only private-college list read is BIEK's, for
  Karachi (SI-18); none elsewhere (PI-14, KI-13, II-12)".
- Add the gaps II-10, II-11, GI-06 and LI-02.
- D13: change it to "CNIC/B-Form (SI-11; N-37 for equivalence applicants), IBCC equivalence (II-08, AI-04, N-36-N-39),
  required only on a condition that the student's qualification is foreign or O/A-level". Drop N-13, which moves to P4,
  and N-40 and N-41, which are attestation. Drop "the O-level statement (N-32)", because no line requires it. N-32 and
  N-34 are the equivalence rules, not a document need.

**F. Make D13 list R-40 explicitly.**
- Fix: list every R-40 type and its phase. For example: CNIC/B-form/Juvenile Card, domicile, character, migration,
  IBCC equivalence, SSC/HSSC mark sheets and certificates, and O/A-level statements in P3; entry-test result card and
  fee challan receipt in P3 or P4.
- Say that `ssc_certificate.v1` and `hssc_certificate.v1` already exist (documents/types/) and are reused or versioned.

**G. Q5 must not read the document directly (R-01).**
- Fix: change it to "the student's board from StudentFacts (the Vault, confirmed from the SSC document through the
  reconciler), matched to a registry board through its aliases". OS documents only propose a value (master §4).

**H. Mode facts and trust.**
- Problem: in D3, "set only by checkers from the walkthroughs" is ambiguous, and `application_route` is not high-stakes
  (fact_classes.yaml:24), yet the mode decides a plan's whole shape.
- Fix: "the fact's source is the official URL and quote the walkthrough line cites. It enters through the P2
  import/review lane. A step set gated by the mode stays provisional until the fact is `verified`." Alternatively, make
  `admission_mode` a high-stakes class, as an owner question.
- Add the `admission_mode` entry to `fact_classes.yaml` `fields:` in T3.

**I. Task plan fixes.**
- T2 needs **T1**, because it reads the playbook's `family` field.
- T10 needs **T1, T3, T4, T8, T11** and the Q2 answer. The table says T1 and T4 only, while the Order says T4 and T11.
  Make the two agree.
- T11 also needs T2, because `admits` to a programme needs the programme rows to exist (store.py:287-290).
- T13 also needs the Q3 answer, T9 (fixtures for replay) and R-13 (place preference and domicile filter). Add
  `pai_os_bridge.py` to its touched files.
- T14 needs **T10** as well as T9. The label test must render the real pk_intermediate per region.
- Add a small data task: `session` in intakes/terms.yaml (Q2).
- Add the D14 flag (point A) to T1 and T14.
- R-ID coverage against the §12 P3 gate is complete:
  - R-36 (T1, T2, T4, T5, T9, T10)
  - R-38 (T3, T4, T9, T10, T11, T12)
  - R-39 (T7)
  - R-40 (T8)
  - R-49 (T2, T13)
  - R-81 (T0)

**J. Small text fixes.**
- Name the file in every "models.py" citation (`playbooks/models.py` or `os/models.py`).
- §1 table: ICT is "per institution under one FDE policy; FDE sets the merit-list dates (II-01, II-09)", not purely
  "each college admits for itself".

## 6. Open questions

Q1 to Q5 are the right questions, and the defaults are sensible apart from Q5 (point G).

Add these:
- **Q6, Spike 2 cost.** Spike 2 involves a billed run, and the owner's rule is no money. Ask: "Is Spike 2 run on free
  or local models only, or what is the cap?" *Default:* no billed run.
- **Q7, the Balochistan gate.** Does a plan that is provisional throughout, never guessed, count as "correct" for the
  §12 gate "every region"? *Default:* yes, with LI-03 to LI-05 recorded as gaps.
- **Q8, the release flag.** Should the route stay off in production until the P5 pilot (point A)? *Default:* yes.
- Optional: should `admission_mode` be high-stakes (point H)?
