# Placement AI: one connected system for every Pakistani student (design)

Status: **draft v3.3 for owner review** · 2026-11-03 (v3.1 adds R-70 to R-72 from research batches 1–4; v3.2 adds R-73 to R-76 from the v2 re-verification; v3.3 applies the pre-development review: R-77 to R-81, the freeze exception process, a real launch-gate denominator, P0 setup tasks, phase per §6 row) · Owner: MSAQLAIN
Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md`. Builds on branch `pai-merge` (`cefa0a4`), where PAI OS
and the PAI Counsellor are merged into one app.
Visual overview (FigJam): https://www.figma.com/board/X25QOs43qaDABBYEmzUPxk (phases and gates, the student's
journey and hand-off, who owns what, fact trust levels, missing and wrong data). The board is a picture of this
document; where they differ, this document wins.

This document is the master spec. Every phase in §12 gets its own spec, plan and build cycle. Each of those must
trace back to the requirement IDs (R…) in §3. A requirement with no phase, no test or no gate is a defect in this
document.

---

## 0. How to use this document (for people and for Claude)

1. **Read §1–§3 first.** They hold the decisions and the full requirement list. Nothing outside §3 is a requirement.
2. **Each phase spec** (`docs/superpowers/specs/<date>-<phase>-design.md`) starts with a table listing every R-ID it
   covers, copied from §12, and the test that proves each one.
3. **Each phase plan** names, per task, the R-IDs it builds.
4. **Every requirement has at least one test** tagged `@pytest.mark.req("R-xx")` (backend) or `// req: R-xx`
   (frontend). `scripts/check_traceability.py` fails CI when an R-ID assigned to a finished phase has no tagged test
   (§13.1).
5. **A phase is done only when its gate (§12) passes in full,** its handoff is written, and both owners sign it off.
   The owners are the **Counsellor lead** (MSAQLAIN, `@memsa771-hub`) and the **integration owner**, one of the OS
   developers (`@10Faheem`, `@MusawirKtk`) named in §15 Q5. Until Q5 is answered, P0 task 0 can start but no gate can
   be signed.
6. **When a step is unclear or a test can't pass as written: stop and ask the owner.** Never improvise, never weaken a
   test, never invent data.

---

## 1. What we are building

**Placement AI** is one app with two parts:
- **PAI Counsellor** gets to know the student, shows the paths open to them, and helps them choose a field and then
  the places to apply.
- **PAI OS** takes that choice and runs it end to end: a dated plan, researched official facts, documents,
  applications, entry tests, merit lists, fee deposits, deadlines, reminders and changes, until the student is
  admitted. It also works on its own when the Counsellor is switched off.

**Who it serves:**

| Step | Coverage |
|---|---|
| **Matric / O-levels → intermediate / A-levels** | Every stream: FSc Pre-Medical, FSc Pre-Engineering, ICS, I.Com, FA / Humanities, General Science, and A-levels with any subject combination. Every government and private college and A-level school, in every region: Punjab, Sindh, KP, Balochistan, Islamabad, AJK, Gilgit-Baltistan. **Not included:** DAE / polytechnic diplomas, cadet colleges |
| **Intermediate / A-levels → bachelor's** | Every bachelor's field: medicine, dentistry, allied health, pharmacy, engineering, computing, business, sciences, social sciences, arts, agriculture, law and every other. Every public and private university in every region, through every admission system: national and provincial entry tests, university tests, central admissions, IBCC equivalence. **Bachelor's degrees only:** no associate degrees, no diplomas |
| **Study abroad** (P6) | Germany, UK and US, bachelor's and master's (Germany master's is built). Requirements R-77 |

---

## 2. Decisions (owner, 2026-11-02)

| # | Decision |
|---|---|
| D-01 | A Counsellor choice hands PAI OS a **complete choice**: field, places, intake and consent. The OS then builds a **complete, researched, sourced plan**. |
| D-02 | **The plan and the roadmap are one thing.** After a choice, the Counsellor's roadmap *is* the OS plan. The Counsellor's own checklist is retired for every route the OS runs. |
| D-03 | **OS Knowledge owns programme and admission facts.** The Counsellor shows them; it doesn't research them separately. |
| D-04 | **No inconsistency.** Every choice, fact and plan change shows the same in both products, whatever the order of events and through crashes. |
| D-05 | **The Counsellor's conversation doesn't change.** The connection changes where data comes from, never how the Counsellor talks. |
| D-06 | **PAI OS is not a study-abroad tool.** In the app it is **"My plan"**. Its pages and words come from the student's route. |
| D-07 | **What the student told PAI reaches the OS:** education, marks, excluded fields, field order, budget, domicile, preferences. |
| D-08 | **Missing or wrong data never breaks a plan or gets overwritten silently** (§7). |
| D-09 | **National coverage.** Two route families, intermediate admission and bachelor's admission, covering all of Pakistan (§1). |
| D-10 | **Complete coverage at the first release.** Every in-scope institution is in the registry, and every high-stakes fact for the coming intake is either **verified** or shown **"not confirmed"** with its official link. |
| D-11 | **Nothing invented.** Official sources only, high-stakes facts verified by a person, unknowns shown as unknown (§8). |
| D-12 | Abroad routes come after the Pakistani families (phase P6): **Germany, UK and US, bachelor's and master's** (Germany master's exists). |
| D-13 | **Facts are researched first by Claude and delivered as spreadsheets.** Data checkers verify them in the spreadsheet and send it back; the import makes them `verified` (§8.6). |
| D-14 | **Guardian consent by email verification:** the student enters a guardian's email, and the guardian confirms through a verified link. |
| D-15 | **No Urdu screens.** Urdu official notices **do** count as sources (OCR; the quote kept in Urdu). |
| D-16 | **The OS developers build all the connection work, Counsellor side included.** Counsellor files still need the Counsellor lead's review. |
| D-17 | **Every year, every intake.** PAI is built for continuous use across admission cycles, not one cycle. 2027 is the first target (§8.7): the **first live intakes** are those whose applications open after the P5 launch (planned mid-2027): 2027 intermediate admissions, Fall 2027 public-university bachelor's admissions, and the 2027 MDCAT and 2027-28 medical/dental cycle. Bachelor's intakes that close before launch (e.g. IBA Karachi and LUMS Fall 2027, deadlines Dec 2026–Jan 2027) are served from their Fall 2028 cycle. |

---

## 3. Requirements (the complete list)

### A. Connection and consistency
| ID | Requirement |
|---|---|
| R-01 | One owner per piece of data, as in §4. Everyone else reads it live through a port and never stores a copy. |
| R-02 | Every choice change carries a `decision_version` that only goes up. The OS applies only newer versions; older or repeated deliveries change nothing. |
| R-03 | The decision change and its outbox row are written in one transaction. Delivery is immediate, plus a sweep every ≤ 5 minutes that compares versions per student. |
| R-04 | Every change in §6 shows the same result in both products within one sweep. |
| R-05 | A nightly consistency job and an end-of-test check run every rule in §9.3. Any mismatch opens a support case. |
| R-06 | Withdrawing a choice stops the plan: no new tasks, open reminders cancelled, closed with reason `withdrawn`. |
| R-07 | The OS never changes the choice. A choice change it needs is a proposal; once the student accepts, it is sent as a `choice_request` and the Counsellor writes it. |
| R-08 | A self-serve plan is adopted (not refused) when the Counsellor module is switched on and the student agrees. |
| R-09 | With the Counsellor on, the OS route builder writes choices through the Counsellor decision service. With it off, the OS works standalone as today. |
| R-10 | Hand-off consent (`authorized_at`) is required. Under-18s also need a guardian's consent (`guardian_authorized_at`), given by email verification (D-14): a one-time link to the guardian's email, expiring, single use, with an audit record. Withdrawing it pauses the plan (§6.15). |
| R-11 | Escalations accept all five reasons, and the student is taken back to choosing with the reason. |
| R-12 | A crash anywhere loses nothing and duplicates nothing (proven like Spike 3). |

### B. The student's own information
| ID | Requirement |
|---|---|
| R-13 | The OS reads education level, marks, entry-test scores, excluded fields, field order, budget, domicile and place preference from the Vault (`StudentFacts`), each with its evidence level. |
| R-14 | The OS works out which levels and routes a student can apply for from the Vault, so it never offers a route the student isn't at (for example, master's to an FSc student). |
| R-15 | An excluded field disappears everywhere at once: paths, chat cards, roadmap, stage H, the OS programme list, the route builder. A planned place that breaks a new constraint becomes a proposal, never a silent removal. |
| R-16 | Marks have one owner, the Vault, whether said in chat, typed in onboarding or read from a mark sheet. Every field the OS reads from a document is compared with the Vault, not only the degree. Intermediate marks are stored **per part** (Part-I and Part-II separately, plus the total), because many universities count Part-I only (R-73). |

### C. Missing and wrong data
| ID | Requirement |
|---|---|
| R-17 | A plan is built even when data is missing. Each missing fact or document becomes a **provide** step, dated backwards from the deadline it feeds. Dependent steps show as blocked with the reason, and eligibility shows "unknown", never "not eligible". |
| R-18 | Each playbook step declares the **evidence level** it needs (`stated` / `shown` / `confirmed`). A request closes only when that level is met. |
| R-19 | **One open request per fact per student.** The OS owns it, it is shown in the plan, the inbox, email and app notification, and answering anywhere closes it everywhere. |
| R-20 | Data that doesn't exist yet (a result not out) becomes a **result expected** step dated from the official exam calendar, followed by a provide step. |
| R-21 | Conflicting data (document vs Vault, document vs document, an impossible value, a student correction) becomes a **which is right** step showing both values and their sources. The steps that use the fact pause; the answer is written to the Vault with its evidence. |
| R-22 | Unanswered requests: reminders, then deadline at risk, then a proposal (drop or swap the place), then an escalation if every place is affected. The plan never fails silently. |

### D. Accuracy
| ID | Requirement |
|---|---|
| R-23 | Every outside fact shown to a student is a Knowledge record with an official URL, an exact quote, the date checked, the intake year and a status. |
| R-24 | **Only listed sources count.** Each region and route has a list of official domains (regulators, boards, admission bodies, HEC, institutions). A fact from any other domain is rejected. Forums, prep sites and social media never count. |
| R-25 | **Three levels:** `unconfirmed` → `confirmed` (the automated trust checks pass) → `verified` (a person checks the source and a second person approves). High-stakes classes (deadlines, merit formulas, eligibility thresholds, seat categories, fees, test dates, test syllabus and pattern) show as fact only when `verified`. Below that they show "not confirmed" with the link. |
| R-26 | **Intake year is strict.** A fact for another year is shown labelled with its year ("2026 closing merit"), never as the current year. |
| R-27 | **Admission season monitoring.** Official pages for the current intake are re-checked daily. A change sets the fact back to `unconfirmed`, pauses the affected steps, notifies affected students, and puts the fact in the review queue. |
| R-28 | Students and parents can report a fact as wrong. It goes back to `unconfirmed` at once and into the review queue. |
| R-29 | AI never supplies a fact from its own knowledge. A research quote must appear word for word in the page actually fetched (existing rule), including scanned PDFs read by OCR and Urdu notices. |
| R-30 | Durations without an official figure are marked `estimate: true` and labelled "estimated" to the student (existing rule). |
| R-31 | Merit formulas and past closing merits are Knowledge facts. `MeritCheck` computes a student's aggregate from Vault marks and the verified formula, or answers "not confirmed". It never predicts a chance. A **closing merit** is the lowest aggregate admitted in a category on the final list of the cycle, and is recorded only when the list is shown to contain everyone admitted (not only the candidates who moved in that round); otherwise it is stored as "lowest on list N", not as the closing merit. |

### E. National coverage
| ID | Requirement |
|---|---|
| R-32 | An **institution registry** holds every in-scope college, A-level school and university in every region, built only from official lists. Each record has an ID, the official source and the date checked. |
| R-33 | The registry also holds **programmes and streams** per institution and campus, **admission bodies**, **admission systems** (central, per institution, test-based), **entry tests**, **seat categories** and **intake calendars**. |
| R-34 | Every institution shows its **coverage level** to students and staff: `listed` (in the registry), `researched` (facts read, not all verified), `verified` (every high-stakes fact for the coming intake verified). |
| R-35 | **Launch gate (D-10).** (a) **Denominator:** for each region and institution type, one named official list with its date (e.g. the HEC recognised list for universities; the provincial department's college list; for A-level schools and private colleges, the board's affiliation list). The registry holds 100% of each list. (b) **Verified floor:** for every institution whose first-live intake (D-17) is open, 100% of its deadlines, merit formulas and eligibility thresholds are `verified`. (c) **Everything else** high-stakes is `verified` or shown "not confirmed" with the official link. (d) Institutions with no official online information stay `listed` and are offered only with a "PAI can't run this place yet" label. The gate is read per family and region from the dashboard. |
| R-36 | **Two route families as data:** `pk_intermediate` and `pk_bachelor`. They are filled in per region, admission body, admission system and institution type from the registry. Never one playbook per institution, never Pakistani names in code (invariant 12). |
| R-37 | The `bachelor` family covers every admission system: national and provincial tests (e.g. MDCAT, ECAT), university tests, central admissions with ranked preference lists, per-university applications, and IBCC equivalence for O/A-level students. |
| R-38 | The `intermediate` family covers every stream and region: college merit, provincial and board rules, domicile, and A-level schools' own admission. |
| R-39 | New replan events: `merit_list.published`, `merit_list.not_listed`, `merit_list.next_round`, `fee_deposit.due`, `test.result_published`, `admission.schedule_changed`. |
| R-40 | New document types as data: CNIC / B-form / NADRA Juvenile Card (under 18), domicile, character certificate, migration certificate, IBCC equivalence, matric and intermediate mark sheets and certificates, O/A-level statements, entry-test result cards, fee challan receipt. |
| R-41 | The contract `level` gains `intermediate` (contract v2). |
| R-42 | A **review queue** for data checkers: the source snapshot with the quote highlighted, approve or reject, two-person rule for high-stakes facts, and an audit log of who verified what and when. |

### F. Counsellor and conversation
| ID | Requirement |
|---|---|
| R-43 | **Frozen in connection work:** Counsellor prompts, conversation policy, the reply pipeline, the model settings and `COUNSELOR_V3_PROMPTS.md` (§10). A CI check blocks a connection PR that changes them. |
| R-44 | Data the Counsellor reads from the OS (programme facts, plan, check-ins, merit) arrives in **the same data shape** it reads today. |
| R-45 | The OS adds **no chat messages.** Plan events show on screens, cards, notifications and email only. New chat behaviour is a separate change with the owner's approval. |
| R-46 | **Proof per PR and per phase:** offline replay unchanged; stage A–I replay with the connection off and on identical apart from fact values; a live graded run (opt-in, cost cap) before real students, with scores not dropping. |
| R-47 | **Counsellor fixes** from the live run: an excluded field stays dismissed (C1); one failed analysis never blocks later ones, including the stage H gate (C2, G4); every "I'll check" runs or the student is told it couldn't (C3); chat cards and the roadmap read one path list (C5); the reply language follows the live-run finding C6; onboarding asks for marks (C7, with R-80). C4 (no merit answer) is R-48. These fixes change *what* the Counsellor says in those cases, never its style, and each goes through the freeze exception process (§10). |
| R-48 | Merit and admission questions in the Counsellor are answered from `MeritCheck` and `ProgrammeFacts` only. |
| R-49 | Stage H lists places from the OS registry and programme list, filtered by the student's constraints, with each place's coverage level. |

### G. In the app
| ID | Requirement |
|---|---|
| R-50 | "Study abroad plan" becomes **"My plan"** everywhere: `en-US.ts` (key `nav.studyAbroadPlan` renamed), `os-nav-group.tsx`, `os-header.tsx`, `shell.tsx`, `counselor/workspace/shell-parts.tsx` (command palette), `os/plan-card.tsx` and `os/vault-strip.tsx` (the `Plane` icon), and their tests. A test fails on "abroad", "visa" or a plane icon on a non-abroad route. |
| R-51 | Each route declares its plan pages. The menu shows the pages of the student's plan (no visa page on Pakistani routes). |
| R-52 | Step titles, page titles and pack wording come from route data, never another route's words. |
| R-53 | "My plan" is visible from the start, with an empty state before a choice. (This deliberately changes today's behaviour, where it appears only from stage H: `os-nav-group.tsx`.) |
| R-54 | Every fact on screen shows its source link, the date checked, and its level (verified / not confirmed / estimated). |
| R-55 | A label test renders every route (fake routes included) and fails on another route's country, body or document name. |

### H2. Every year, every intake (D-17)
| ID | Requirement |
|---|---|
| R-60 | Every cycle-bound fact (dates, merit, fees, seats, test dates, formulas) is stored per **intake** (term and year). Standing facts (an institution exists, its official site) are stored once. Nothing is overwritten by a new year. |
| R-61 | **Yearly rollover:** for each region and family, a new intake is opened from the previous one's structure. Every cycle-bound fact starts `unconfirmed` for the new intake, research reruns, and checkers verify. Last year's values stay visible, labelled with their year, until the new ones are verified. |
| R-62 | More than one intake per year (e.g. spring and fall) works the same way. |
| R-63 | A student can plan for any open intake. Planning for an intake whose facts aren't published yet uses last year's facts, labelled, with steps that update automatically when the new facts are verified (§6.10). |
| R-64 | A student who doesn't get in, or chooses to wait, can start a new plan for the next intake with everything they already gave PAI kept. |
| R-65 | Playbooks are versioned per intake. Running plans keep their pinned version, and changes reach them only as revisions (parent spec 4.3). |
| R-66 | The coverage dashboard and the launch gate (R-35) are per intake. Each new intake must pass its own gate before students plan for it as "current". |

### H3. Research spreadsheets (D-13)
| ID | Requirement |
|---|---|
| R-67 | One fixed spreadsheet format for research batches (§8.6): an Institutions sheet, a Programmes sheet and a Facts sheet, with columns for checker 1 and checker 2. Every row has a `read_method`. The **Programmes sheet has one canonical layout** for every batch: `programme_id, inst_id, campus, programme, level, field, intake, seat_category, seats, closing_merit, closing_scale, test_options, min_ssc, min_hssc, required_subjects, merit_formula, source_url, quote_verbatim, read_method, retrieved, claude_status, claude_note` + checker columns; unused columns stay empty. Status values are fixed: `found / unconfirmed / conflict / not_readable / not_found / lead_only / superseded`. |
| R-68 | An import script validates a returned spreadsheet (format, URLs on the allow-list, quotes present, both checkers filled for high-stakes facts) and loads it into Knowledge. Rows that fail are listed, never loaded silently. Every import is logged and can be undone. Rows whose `read_method` is model-extracted (e.g. WebFetch) or machine-read from an image are **re-fetched and the quote matched word for word** before they can become `confirmed`; a row that doesn't match stays `unconfirmed`. Older batch layouts are mapped into the canonical one (R-67) by the import, not by hand. |
| R-69 | The same format is the export of the review queue (R-42), so spreadsheets and the queue never disagree. |

### H4. Lessons from research batches 1–4 (2026-11-03)
| ID | Requirement |
|---|---|
| R-70 | **Merit shown only inside the student's login.** When an admission body shows the merit list only in each candidate's own portal account (KMU, SZABMU, JSMU and LUMHS in 2026-27), the plan adds a **share your merit position** provide step on the list's publication date (evidence `shown`: a screenshot of the portal page). The OS never asks for, stores or uses the student's portal password and never logs in for them. The value is a Vault fact marked `student_reported`, used only for that student's next steps (claim, fee, upgrade lists). It never becomes a public closing merit: those come only from public lists (R-31). |
| R-71 | **Content integrity, not only the domain.** A page on an allowed domain (R-24) is used only if it passes integrity checks: no injected spam (gambling or link-farm patterns, a sudden flood of links to unrelated domains), no unexplained wholesale change, valid TLS, and no redirect from the allowed domain to a domain that is not on the list (seen: biselrk.edu.pk → biselrk.com). When two domains claim to be the same body, the `.edu.pk` / `.gov.pk` one is preferred and the other is `suspect` until a person confirms it. A failed check marks the domain `suspect`: its facts drop to `unconfirmed`, nothing new is taken from it, and a person is alerted in the review queue. Example found in research: the AJK board homepage (ajkbise.net) carries hundreds of injected gambling links. |
| R-72 | **Official sources that can't be read automatically** (blocked, login-only, scanned with failed OCR, image-only notices, JavaScript-rendered pages that a headless browser also fails on) are marked `not_readable` in the registry and go to the checkers for human collection: the checker saves the official document or a screenshot and uploads it with the spreadsheet row as evidence. A copy on a secondary site (news, prep or social pages) may be used only as a lead to find the official document, never as the fact's source. Facts read by machine from an image are `unconfirmed` until a checker compares them with the original. |
| R-73 | **Intermediate Part-I marks are high-stakes.** When the student's target universities count Part-I only (GCU, QAU, PIEAS, MUET, UET Lahore, NED found so far), the plan asks for the Part-I mark sheet (evidence `shown`) as soon as the plan is built, and `MeritCheck` uses exactly the parts the formula names. |
| R-74 | **Research reads pages with a headless browser** when a plain fetch returns a JavaScript shell (SECCAP). Only if that also fails is the source `not_readable` (R-72). |
| R-75 | **A threshold has an owner.** Eligibility thresholds are stored against the body that sets them (the regulator, or the admitting university), never merged. When an admitting body states a figure and attributes it to the regulator, but the regulator's own document doesn't state it, both are recorded and the fact is a `conflict` for a person to settle; the admitting body's figure is still the rule for that body's admissions. (Example: KMU, SZABMU and the AJK JAC state MDCAT 55% MBBS / 50% BDS, two of them citing PMDC; PMDC's Admissions Regulations 2025 as read state no pass mark.) |
| R-76 | **One vocabulary for regions and statuses.** Regions: Punjab, Sindh, Khyber Pakhtunkhwa, Balochistan, Islamabad Capital Territory, Azad Jammu and Kashmir, Gilgit-Baltistan (plus `national` and `federal-institution`). Research and Knowledge use only these spellings; the import normalises others. |

### H5. From the pre-development review (2026-11-03)
| ID | Requirement |
|---|---|
| R-77 | **Abroad routes (D-12, P6):** Germany bachelor's, UK bachelor's and master's, US bachelor's and master's, each with its walkthrough, allow-list, registry, playbook, research batches and launch gate, as for Pakistan. Any new Counsellor chat behaviour for abroad (e.g. offering master's abroad to bachelor's graduates) is a separate owner-approved change (R-45). |
| R-78 | **Constraints reach the Vault from one source.** Today exclusions live as `pai_possibilities.status = 'dismissed'` (`models.py`) and field order nowhere the OS can read. P1 projects dismissals and field order into the Vault (migration + reconciler), and from then on the Counsellor's own filters (C1) and `StudentFacts` both read the Vault. Possibilities keep their status for the journey UI but are no longer the source of an exclusion. |
| R-79 | **The hand-off is built, not assumed.** `app/pai_c/os_export.py` doesn't exist and nothing calls `decision_changed`. P1 builds: the export; choice columns (places 1–5 with rank, intake, level, `decision_version`, `os_supported`, `guardian_authorized_at`); one new decision row per version (rows are never rewritten, as today); the call to `decision_changed` in the same transaction as the outbox row; and a sweep keyed on `decision_version`, so withdrawals are swept too. |
| R-80 | **Onboarding asks for marks** (matric, intermediate Part-I and Part-II separately, or O/A-level grades), written to the Vault with evidence `stated` (R-16, R-73). Marks are never asked again in chat once known. |
| R-81 | **Route families are designed before they are built.** Before P3, an ADR defines how one family playbook is compiled per region, body and system from the registry (today's compiler handles one playbook per route and `external_ref` is `{journey}:{country}:{level}`), including how a decision maps to a family instance. P3 and P4 start only after it is approved. |

### H. Process
| ID | Requirement |
|---|---|
| R-56 | Every phase: spec → plan → subagent-driven build → gate → handoff → owners' sign-off. One branch per task, cut from the integration branch (§13). |
| R-57 | Requirement traceability check in CI (§13.1). |
| R-58 | Fake routes (Ireland master's, PK BS) stay in the tests. A red-flag search fails on Pakistani or other country-specific names in `app/os` **Python code** (`*.py`); playbooks, seeds and tests are data and are exempt. |
| R-59 | Every phase passes the full suite: `tests/os`, the Counsellor legacy suite, the standalone suite with the Counsellor off, Tach, the Alembic check (one head per migration tree: `versions/` and `versions_os/`), frontend tests, `tsc` and the build. The CI jobs that don't exist yet (frontend, `tsc`, build, standalone) are added in P0. |

---

## 4. Who owns what (R-01)

| Data | Owner (only writer) | Others read it through |
|---|---|---|
| Student facts: identity, education, marks, test scores, city, country, domicile (the Vault) | Counsellor Vault, via its reconciler, with evidence | OS: `StudentFacts` |
| Student constraints: excluded fields, field order, budget, place preference | Vault (recorded from chat, with the student's words as evidence) | OS: `StudentFacts` |
| Facts read from documents | OS documents *propose*; the Vault reconciler *writes* after the student confirms | Vault evidence links to the document |
| Document files | One store, one upload entry point | Both: by document ID |
| Journey stage, paths, the Mirror, the Truth Map | Counsellor | OS never reads them |
| **The choice** (field, level, destination, places, intake, consent) | Counsellor decision service (with the Counsellor on); OS route builder (with it off) | OS: decision export by version |
| Institution registry, programmes, admission bodies, tests, merit formulas, closing merits, calendars | OS Knowledge | Counsellor: `ProgrammeList`, `ProgrammeFacts`, `MeritCheck` |
| Field cards before a choice | Counsellor roadmap engine, reading entry rules from OS Knowledge | — |
| **The plan**: steps, dates, status, requests, documents needed, packs | OS kernel | Counsellor: `PlanView` |
| Ticks and actions on plan steps | OS (inbox actions through the OS API, from any screen) | Counsellor: `PlanView` |
| Requests to the student | OS (one per fact) | Counsellor: `PlanView` |
| Escalations | OS raises them; the Counsellor owns what happens next | Both: by key |

Retired for routes the OS runs: the Counsellor checklist (`RouteDecision.steps`, `steps_done`) and stage H's own
research (`paths/programs.py`). They stay only for routes the OS can't run yet, clearly labelled "PAI can't run this
plan yet".

---

## 5. The student's journey

1. **Stages A–G (Counsellor, unchanged).** Field cards read entry rules from OS Knowledge.
2. **Stage H, where to study.** Places come from the OS registry, filtered by the student's constraints and showing
   coverage levels and sourced facts. Merit questions are answered by `MeritCheck`.
3. **Stage I, choose.** The student picks 1–5 places in order, an intake and consent (a guardian's too, for under-18s).
   The decision service writes version n and an outbox row in one transaction.
4. **Hand-off.** Immediate delivery, with the sweep as backup. The OS builds or revises the plan.
5. **Stage J, the plan.** The roadmap screen is `PlanView`. "My plan" pages are the detail views.
6. **Stage K, stay with them.** OS events appear on screens, in notifications and by email. The Counsellor's chat is
   unchanged.

---

## 6. Every change and what happens on both sides (R-04)

Each row is a scripted test (§13). Rows are tested in **P1**, except 6.10 and 6.23–6.25 (need Knowledge, the review queue, monitoring and `MeritCheck`: tested in **P2**) and 6.20 (needs official calendars: **P2**).

| # | Change | Who writes | OS | Counsellor shows |
|---|---|---|---|---|
| 6.1 | Choose field, places, intake | Decision service (v = n) | Builds plan | Roadmap = plan |
| 6.2 | Change places, order or intake | Decision service (n+1) | Revision; started and done steps kept | Plan with "what changed" |
| 6.3 | Change field, destination or level | Decision service (n+1) | Old plan closed (`replaced`); new plan | New plan; old one in history |
| 6.4 | Withdraw | Decision service (n+1, `withdrawn`) | Plan stopped (R-06) | Back to choosing |
| 6.5 | OS needs a choice change (place closed, ineligible, deadline passed) | None: a proposal | Waits on the student | Proposal on the plan |
| 6.6 | Student accepts the proposal | `choice_request` → decision service (n+1) | Revision via 6.2 | Same version both sides |
| 6.7 | Document uploaded (any screen) | One upload → OS documents | Uses confirmed fields | Vault shows it; facts enter the Vault after confirmation |
| 6.8 | Vault fact changes | Vault reconciler | `fact_changed` → replan | Field cards and plan use the new fact |
| 6.9 | Constraint changes (exclusion, order, budget, domicile, preference) | Vault reconciler | Re-filters; a broken place → proposal | Excluded field gone everywhere (R-15) |
| 6.10 | Programme or admission fact changes | OS Knowledge | Replan → revision if needed | Same live fact |
| 6.11 | Step done or ticked (any screen) | OS kernel | Records it | Same tick via `PlanView` |
| 6.12 | Route impossible | OS escalation | Plan paused | Back to choosing, with the reason |
| 6.13 | OS builder used while the Counsellor is on | Decision service | As 6.1 or 6.2 | Same choice |
| 6.14 | Choice of a route the OS can't run | Decision service (`os_supported = false`) | Nothing | Labelled guidance checklist |
| 6.15 | Guardian gives or withdraws consent | Counsellor consent record | No plan, or plan paused | Consent state |
| 6.16 | Counsellor switched on with a self-serve plan | Decision written from the plan, the student agreeing | Plan adopted (R-08) | Same plan |
| 6.17 | Counsellor switched off | — | Plans continue; OS builder writes choices | Plan pages still reachable |
| 6.18 | Plan finished | OS | `plan.finished` | Stage K |
| 6.19 | Data missing | OS: provide step | Dependent steps blocked (R-17) | Request on the plan |
| 6.20 | Data not available yet (result due) | OS: result expected step | Dated from the official calendar (R-20) | Same step |
| 6.21 | Data conflicting | OS: which is right step | Dependent steps paused (R-21) | Same step; the answer goes to the Vault |
| 6.22 | No response | OS | Reminders → at risk → proposal → escalation (R-22) | Same states |
| 6.23 | A fact is reported wrong | Knowledge (status reset) | Affected steps paused; review queue | "Not confirmed" on screen |
| 6.24 | An official page changes in season | Knowledge (status reset) | Affected steps paused; students notified (R-27) | Same |
| 6.25 | Merit question asked | None (a read) | `MeritCheck` | Answer from `MeritCheck` only |

---

## 7. Missing and wrong data (R-17 to R-22)

- **Missing data:**
  - The plan is built anyway, and each missing item becomes a provide step.
  - The step says what is needed, which evidence level counts ("type your marks" vs "upload the mark sheet"), and the
    date it's needed by.
  - Typing marks in chat updates the Vault and closes "tell us your marks", but not "upload the mark sheet".
- **Not available yet:** the plan includes "result expected <date from the board's calendar>" and then a provide
  step. The board and exam calendars are Knowledge facts. The Counsellor's existing calendar data
  (`academic_calendar.json`) moves into Knowledge with official sources.
- **Conflicting data:**
  - It is found in four ways: a document vs the Vault (every field), a document vs another document, an impossible
    value (above the board's maximum, for example), or a student correction.
  - The student picks the right value, shown with both sources.
  - Nothing is overwritten silently, and dependent steps pause until the student answers.
- **No response:** reminders on the playbook's schedule, then deadline at risk, then a proposal to drop or swap the
  affected place, then an escalation when every place is affected.
- **One request per fact:** the consistency check fails on two open requests for the same student and fact.
- **Merit only visible in the student's login (R-70):** on the date the provisional or selection list is due, the
  plan asks the student to share their merit position with a screenshot. The OS never handles their portal
  password. The answer drives that student's claim, fee and upgrade steps only.

---

## 8. Accuracy and the national data system (R-23 to R-42)

### 8.1 Where facts come from
- **Official sources only, in this order:**
  1. regulators and national bodies (HEC, the medical and engineering regulators);
  2. provincial departments and boards;
  3. admission bodies;
  4. the institutions themselves.
- **One allow-list of domains per region.** It is part of each region's walkthrough (§8.4), reviewed by a person, and
  enforced in code (R-24). Being on the list is necessary but not enough: each fetched page must also pass the
  integrity checks (R-71), and a domain that fails is marked `suspect`.
- **Sources that can't be read** (blocked, login-only, scanned, image-only) go to the checkers for human collection
  with saved evidence (R-72). Copies on secondary sites are leads only.
- **Reading:**
  - HTML pages;
  - PDFs, including scanned notices and merit lists, through OCR (Docling);
  - Urdu notices (Q6).

  A quote must appear in the text actually read (R-29).

### 8.2 Levels of trust (R-25)

| Level | Means | Shown to the student as |
|---|---|---|
| `unconfirmed` | Found, but a trust check failed or not yet read twice | "Not confirmed", with the link |
| `confirmed` | Official source, read twice and agreeing, right intake year | The fact, with the source (for normal facts) |
| `verified` | Confirmed, then checked by one person and approved by another | The fact, with "verified" and the source (required for high-stakes classes) |

High-stakes classes: deadlines and schedule dates, merit formulas, eligibility thresholds, seat categories and quotas,
fees, test dates, test pattern and syllabus.

### 8.3 The registry (R-32 to R-35)
- **What it holds:** institutions → campuses → programmes or streams → intakes. Also admission bodies and the
  admission systems they run, entry tests, seat categories, and calendars (exam, result, admission).
- **How it's filled:** built from official lists only. The exact official lists for each region are named in that
  region's walkthrough (§8.4).
- **Coverage level per institution:** `listed` → `researched` → `verified` (R-34).
- **Coverage dashboard:** per region and per family, how many institutions are at each level and how many high-stakes
  facts are verified or not confirmed. The launch gate (R-35) is read from it.

### 8.4 Walkthroughs (Spike 5 at national scale)
Before any data is relied on, each region and family gets a written walkthrough citing official pages. It covers:
- how admission works;
- which bodies run it;
- which official lists define the institutions;
- the seat categories;
- the documents needed;
- the calendar.

A person checks every citation. The playbooks are written from these walkthroughs.

### 8.5 Season monitoring and the review queue (R-27, R-42)
- **Daily re-checks** of every current-intake source during each region's admission season.
- **A change** resets the fact, pauses the affected steps, notifies the affected students, and queues the fact for
  review.
- **The review queue** (an admin screen): the snapshot with the quote highlighted, approve or reject, the two-person
  rule, and an audit log.
- **Reports from students and parents** (R-28) land in the same queue.

### 8.6 People and the research spreadsheets (D-13)

**Who does what:**
- **Claude researches** each batch from official sources and fills the spreadsheet.
- **2–4 part-time data checkers** verify every row.
- **The developers import** the returned spreadsheet.

**The loop:**
1. **Claude researches a batch.** Every row carries:
   - the entity;
   - the field;
   - the value and its unit;
   - the intake;
   - the source URL and its type (HTML, PDF or scan);
   - the exact quote, and its language;
   - the date and time read;
   - how it was read (fetch or OCR);
   - Claude's status (`found` / `unconfirmed` / `conflict` / `not_readable` / `not_found` / `lead_only` / `superseded`) with a reason.

   Claude never fills a value it didn't read on an official page; `not_found` is a valid row. A row replaced by a newer intake is `superseded` and kept as history, never deleted (R-60).
2. **Checker 1** opens each source and marks it `correct` / `wrong` / `unclear`, adding a corrected value with its own
   quote if wrong.
3. **Checker 2 approves** high-stakes rows (the two-person rule).
4. **The returned file goes back to Claude,** who:
   - re-checks every row marked `wrong` or `unclear`;
   - lists disagreements for the owner;
   - runs the import (R-68).
5. **Only rows that both checkers accepted become `verified`.**

**Batch order (registry backbone first, then down to institutions):**
1. **National:**
   - HEC-recognised universities and degree-awarding institutions;
   - every examination board (provincial boards, the federal board, other recognised boards) and IBCC;
   - the professional regulators;
   - the national and provincial entry tests.
2. **Per province and region:** the admission bodies and systems (central admissions, college admission rules),
   domicile and seat categories, and the exam and result calendars.
3. **Per university:** admission pages, tests, merit formulas, schedules and fees, region by region.
4. **Per college:** from the provincial official lists. Many colleges publish nothing online, so they stay `listed`
   with their official list as the source until a checker or the college confirms more.

**What a batch can and can't hold:**
- **Timing.** In November 2026 most 2027 admission notices are not out yet. Batches hold standing rules plus the
  latest published cycle, labelled with its year (R-26, R-63). The 2027 facts are added as they are published (season
  monitoring).
- **Unreadable pages.** Some official sites block automated reading or publish only images. Those rows are marked
  "not readable" with the URL, for a checker to read by hand.

---

### 8.7 Every year, every intake (D-17, R-60 to R-66)
- **Knowledge keys every cycle-bound fact by intake.** Registry entries (institutions, programmes, bodies) persist
  across years and can be marked closed, merged or renamed, with sources.
- **The rollover runs once per region, family and intake,** as a job:
  1. open the new intake;
  2. copy the structure, not the values;
  3. set every cycle-bound fact to `unconfirmed`;
  4. queue the research batches and the spreadsheets for the checkers;
  5. keep last year's values visible, labelled with their year.
- **The calendar** of when each region's notices usually appear is itself Knowledge. It drives when monitoring starts.
- **A new intake becomes "current"** for students only after it passes its own coverage gate (R-66). Until then
  students can still plan for it, with labelled values from last year.

## 9. Mechanics

### 9.1 Contracts (v2; both teams sign off; v1 files stay frozen)

| Contract | What it is |
|---|---|
| `decision_record.v2` | Adds `decision_version`, `status` (chosen / withdrawn), `level` += `intermediate`, `path_ref`, `guardian_authorized_at`, `os_supported` |
| `route_contract.v2` | `level` += `intermediate` |
| `plan_view.v1` | The full plan for the roadmap screen: steps, status, due dates with time zones, owner, dependencies, requests with evidence levels, documents needed, revision and "what changed". No free text |
| `os_event.v1` | OS → Counsellor: plan created / revised / paused / stopped / finished, step done, student needed, deadline at risk, proposal waiting |
| `choice_request.v1` | OS → Counsellor: the accepted change and the version it's based on |
| `student_facts.v1` | Counsellor → OS: education, marks, test scores, constraints, each with its Vault version and evidence level |
| `vault_event.v1` | Counsellor → OS: `fact_changed` with keys and the Vault version |
| `programme_facts.v1` | OS → Counsellor: a programme's facts with level, source, quote, checked date, intake year |
| `merit_check.v1` | OS → Counsellor: formula (sourced), aggregate and the marks used, past closing merits by year (sourced), status per part |
| `escalation.v2` | All five reasons |

### 9.2 Ports
- **The OS offers:** `PlanQuery.plan_view`, `programme_list`, `programme_facts`, `merit_check`, and
  `PlanSource.submit_decision`.
- **The OS consumes:** `StudentFacts.get`, `ChoiceSink.request`, `FactProposalSink.propose`.
- **Glue:** all of it lives in `app/pai_os_bridge.py`. Tach keeps `app/os` free of Counsellor imports.

### 9.3 Consistency rules (R-05)
1. Every active, supported decision has an open plan (or a recorded refusal) at the same version.
2. Every open Counsellor plan has an active decision, and the plan's contract hash equals the decision export hash.
3. Every withdrawn decision has its plan stopped.
4. No Counsellor checklist is active for a route that has an OS plan.
5. Every Vault fact a plan uses is current, or a replan is pending.
6. Every document a plan step needs has a record in the one store.
7. At most one open request per student and fact.
8. No excluded field appears in any plan, stage H list or path list.
9. No fact shown to a student comes from a domain not on the allow-list.
10. No high-stakes fact is shown as fact unless it is `verified`.
11. No fact for another intake year is shown without its year.
12. No fact shown to a student comes from a domain marked `suspect` (R-71).
13. No `student_reported` merit position appears in any public or cross-student figure (R-70).

---

## 10. Protecting the Counsellor's conversation (R-43 to R-47)

| Touch point | Rule |
|---|---|
| Stage H facts | An adapter gives the same shape `paths/programs.py` gives today; only the values change |
| Places, intake and consent | New screens and cards, not chat turns |
| Roadmap, stage J, check-ins | An adapter gives the same fields from `PlanView`; timing and wording don't change |
| OS events | Screens, notifications and email only; no chat messages |
| Escalations | Existing handling and fixed sentences; new sentences need the owner's approval |
| Merit answers | From `MeritCheck` only (R-48), in the existing reply style |

- **Frozen files (exact paths):**
  - `backend/app/pai_c/**/*.md`;
  - `backend/app/pai_c/deep/` (including `deep/prompts/`), `backend/app/pai_c/planner/prompts/`,
    `backend/app/pai_c/policy/prompts/`, `backend/app/pai_c/voice/prompts/`, `backend/app/pai_c/playbooks/`,
    `backend/app/pai_c/policy/actions/`;
  - `backend/app/pai_c/policy/*.json`;
  - the Counsellor model settings;
  - `docs/counselor/COUNSELOR_V3_PROMPTS.md`.

  `backend/app/os/playbooks/` is **not** frozen. CI blocks a PR that changes a frozen path unless it carries the
  `freeze-exception` label, and CODEOWNERS (P0) requires the Counsellor lead on every path under
  `backend/app/pai_c/`, `backend/app/pai_os_bridge.py` and `frontend/components/counselor/`.
- **Freeze exceptions (owner-approved list, nothing else):**
  1. the P0 fixes C1, C2, C3, C5, C6, C7 (R-47) — `deep/analysis.py` and the relevant prompts;
  2. merit answers from `MeritCheck` (R-48) — `deep/prompts/path_analyzer.md` and the reply pipeline's data source;
  3. moving `policy/academic_calendar.json` and `policy/admission_rules.json` into Knowledge, leaving an adapter that
     returns the same shape (§7, §5 step 1).

  Each exception PR carries the label, the R-ID, a replay showing that only the intended answers changed, and the
  Counsellor lead's approval. **The owner accepts** that exceptions 1 and 2 change *what* the Counsellor says in
  those cases (that is their purpose); its style, tone and flow stay unchanged.
- **Flags:**
  - With the Counsellor module off, it behaves byte-for-byte as today.
  - Each part has its own flag (stage H source, roadmap from `PlanView`, check-ins, merit answers).
- **The P0 Counsellor fixes (R-47)** are built by the OS developers (D-16), reviewed by the Counsellor lead, and are outside the freeze. They pass the Counsellor
  evaluations and a replay that shows only the fixed behaviour changed.

---

## 11. In the app (R-50 to R-55)

- **"My plan"** replaces "Study abroad plan" in `en-US.ts`, `os-nav-group.tsx`, `os-header.tsx` and `shell.tsx`.
- **Pages come from the route.** Each playbook declares its pages, and the menu shows the pages of the student's plan.
- **Words come from the route data.** No Germany or uni-assist words appear on a Pakistani plan.
- **Always visible.** "My plan" shows from the start, with an empty state before a choice.
- **Every fact shows its source,** the date checked, and verified / not confirmed / estimated.
- **The label test** renders every route, fake ones included.

---

## 12. Phases, gates and requirement coverage

| Phase | Builds | Requirements | Gate (all must pass) |
|---|---|---|---|
| **P0 Setup and Counsellor fixes** (OS developers, Counsellor lead reviews; starts now) | **Task 0:** cut `pai-connect` from `pai-merge`; rewrite the root and `backend/app/os` `CLAUDE.md` (replace the "pai-c only / PAI OS is another developer's work / branch from pai-os / freeze new modules" rules, §13.2); CODEOWNERS entries (§10); register the `req` pytest marker; `docs/requirements/connection.yaml`; `scripts/check_traceability.py`; the freeze CI check; missing CI jobs (R-59). **Then** C1, C2, C3, C5, C6, C7 | R-47, R-57, R-58, R-59 (CI) | Task 0 merged with CI green; the live-run student reaches stage H with only MBBS and BDS; Counsellor evaluations; replay shows only the fix changed |
| **P1 Connection core** | Contracts v2, versions and outbox, export, consent, `StudentFacts` and constraints, `PlanView` roadmap, retire the checklist, withdraw, proposals → `choice_request`, adoption, one upload entry point, missing and wrong data, sweep by version, consistency job, escalations ×5, conversation freeze and replays, "My plan" with route pages | R-01–R-22, R-41, R-43–R-46, R-50–R-55, R-59, R-78–R-80 | The P1 spec lists every reader of `RouteDecision.steps` to move to `PlanView` (backend: `checkins.py`, `journey_sync.py`, `data_export.py`, `roadmap/engine.py`, routers `roadmap.py`, `tasks.py`, `workflows.py`, `workspaces.py`, `services/workflow.py`; frontend: `roadmap-parts.tsx`, `roadmap-steps.tsx`, `use-journey.ts`, `onboarding-view.tsx`, `lib/api.ts`). Every P1 §6 row passes on fictional students (Germany master's plus the fake PK BS and Ireland routes); consistency check finds zero; crash test; standalone suite; conversation proofs; label test |
| **P2 National data system** | Registry; admission bodies, systems, tests, seat categories, calendars; allow-lists; OCR and Urdu reading; three trust levels with two-person verification; review queue; spreadsheet export and import; intake model and yearly rollover; season monitoring; reports from students; coverage dashboard; `MeritCheck`; `ProgrammeFacts`. **In parallel:** Claude's research batches 1–4 with the checkers (§8.6) | R-23–R-35, R-42, R-48, R-60–R-69, R-71, R-72, R-74–R-76 | Walkthroughs for every region checked; integrity check proven on a page with injected spam; a `not_readable` source collected by a checker with evidence; registry built from official lists; Spike 1 rerun on a sample from every region: **100% correct on verified facts, ≥ 95% on confirmed**; monitoring proven on a scripted page change; a scripted rollover from one intake to the next; a spreadsheet round trip with deliberate errors caught by the import |
| **P3 Intermediate family** | Starts with the route-family ADR (R-81). `pk_intermediate` playbook family from data; every stream and region; new documents and events; stage H for intermediate | R-36, R-38, R-39, R-40, R-49, R-81 | ADR approved; fictional students in every region and stream get correct plans; Spike 2 on the new documents; rehearsal |
| **P4 Bachelor's family** | `pk_bachelor` family; every admission system; IBCC; tests and merit rounds | R-36, R-37, R-39, R-40, R-49, R-70, R-73 | Fictional students across every admission system get correct plans; a login-only merit list handled by the share-your-position step with no password handled; the live-run student gets a correct MBBS/BDS plan and a sourced merit answer; rehearsal |
| **P5 Launch** | Coverage to the launch gate; legal review of the guardian-consent terms (consent itself is built in P1); small pilot per family | R-35, R-56 (R-10 legal review) | Launch gate R-35 read from the dashboard; legal review done; pilot students reach submission; live graded Counsellor run |
| **P6 Abroad** | Germany bachelor's (master's exists), UK bachelor's and master's, US bachelor's and master's. Each gets a walkthrough, playbook, registry and research batches as for Pakistan | R-77, using R-23–R-36 and R-60–R-76 per country | As P3/P4 per country and level |

Every R-ID appears in at least one phase. R-56 to R-59 apply to every phase. R-60 to R-69, R-71, R-72 and R-74 to R-76 are built in P2 and apply to every route after it. R-70 and R-73 are built in P4 and apply to every route after it. R-57 and R-58 are built in P0 and enforced in every phase.

**Order and timing (rough, at the current pace, with data checkers in place):**
- P0 takes 1–2 weeks.
- P1 takes 4–6 weeks.
- P2 takes 6–10 weeks to build, then ongoing.
- P3 and P4 are built alongside P2.
- P5 aims at mid-2027, for the first live intakes named in D-17.
- **Checker capacity is unknown until the registry exists.** At the start of P2, the registry size × high-stakes facts per institution × two checks gives the review workload; the owner then sets the number of checkers against the P5 date. If it doesn't fit, the R-35(b) verified floor is met first for the regions and families with the most students.

The critical path is P2's verification work, not code.

---

## 13. Making sure Claude executes all of it

### 13.1 Traceability
- **The requirement list in code:** `docs/requirements/connection.yaml` lists every R-ID with its phase.
- **Tags:** tests carry `@pytest.mark.req("R-xx")`, and frontend tests `// req: R-xx`.
- **`scripts/check_traceability.py`:** run in CI, it fails when an R-ID of a finished or current phase has no tagged
  test, or when a test names an R-ID that doesn't exist.
- **The gate report** of each phase lists every R-ID with its tests and results.

### 13.2 Rules in `CLAUDE.md` (root and `app/os`; P0 task 0 **replaces** the current branch and ownership rules, which contradict D-16 and §13.4)
- Read this spec's §2–§3 and the phase spec before any task, and name the R-IDs the task builds.
- Never invent data: no institution, date, fee, merit figure or rule from memory. Data enters only through the
  registry, research and the review queue.
- No Pakistani or other country-specific names in `app/os` code: the red-flag search (R-58).
- Don't touch the frozen Counsellor files in connection work (R-43).
- Every change of data ownership follows §4. A copy of another owner's data is a defect.
- Stop and ask when unclear. Never weaken a test to make it pass.

### 13.3 Reviews
- Each task gets an implementer, a reviewer and fix rounds (subagent-driven).
- **The reviewer checks:** the R-IDs are built and tested; nothing hardcoded; no copied data; the frozen files are
  untouched; no invented data.
- **At each phase end,** a separate final reviewer who didn't build the work reads the phase against this spec.

### 13.4 Branches
- **One integration branch for this work,** `pai-connect`, cut from `pai-merge`.
- **Task branches:** `pc/p<N>-t<M>-<name>`, squash-merged.
- **At each gate,** merge into `pai-merge` with a merge commit, tagged `connect-p<N>`.
- **P0 work** is done on `pai-connect` task branches like every other phase.

### 13.5 Handoffs
- Each phase writes `docs/connect/handoff/p<N>-handoff.md`: what was built, the gate report, deviations with reasons,
  and open items.
- The next phase starts by reading it.

---

## 14. Risks

| Risk | Mitigation |
|---|---|
| National verification is too much work for two developers | Data checkers (Q1); the dashboard shows progress; anything not verified is shown "not confirmed", so it is never wrong |
| Official Pakistani sources are late, scanned, in Urdu, or changed mid-season | OCR, Urdu reading, daily monitoring in season, a status reset on change |
| Unofficial sites look official | Allow-list per region, reviewed by a person |
| An official site is hacked (seen: ajkbise.net) | Integrity checks on every fetched page; failing domains marked `suspect` (R-71) |
| Key sources block automated reading or show merit only after login | Human collection with evidence (R-72); student shares their own position (R-70) |
| OS developers changing Counsellor code they did not write | Counsellor lead reviews every PR touching Counsellor files (D-16); frozen files and replays (§10) |
| Retiring the checklist breaks Journey, check-ins or the timeline | P1 lists every reader of `RouteDecision.steps` and moves each to `PlanView` |
| The Counsellor's conversation changes | §10: freeze, same shapes, no chat messages, replays, flags |
| Minors' data | Guardian consent and a legal review before real students (P5) |
| Scope creep | Anything not in §3 needs an owner decision and a new R-ID |

---

## 15. Owner's answers (2026-11-02) and what is still open

| # | Question | Answer |
|---|---|---|
| Q1 | Data checkers | 2–4 part-time checkers. Claude researches first and delivers spreadsheets; checkers verify and return them (D-13, §8.6) |
| Q2 | Guardian consent | Email verification (D-14). **Still open:** who does the legal review of the terms |
| Q3 | Abroad | Germany, UK, US, bachelor's and master's (D-12) |
| Q4 | Urdu screens | No (D-15) |
| Q5 | Who builds | The OS developers build everything, Counsellor side included (D-16). **Still open:** which of the two developers owns integration (merges and gates) |
| Q6 | Urdu sources | Yes (D-15) |
| Q7 | Intake | Every year and every intake (D-17); 2027 is the first target |
