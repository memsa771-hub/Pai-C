# PAI OS v1 — Design Spec

Status: draft for review · 2026-10-12 · Owner: MSAQLAIN
Supersedes: PAI OS Architecture Draft 1 and Draft 2 (HTML page), the first FigJam board, and any conflicting wording in the Build Plan, Explained, Approval and Setup docs. Where those documents disagree with this spec, this spec wins.

---

## 1. Intent

**Outcome.** PAI OS carries out a student's chosen study-abroad route to an outcome (admission and visa, or a documented reason the route can't work). It plans every step, does the steps it can with AI agents and rule-based workers, asks the student for what only they can do, and adjusts the plan when things change.

**For whom.** v1: Pakistani bachelor's graduates applying to English-taught master's programmes at German public universities, one intake, about 30 programmes.

**Success criteria (v1 is done when):**
1. 10–20 pilot students each have a plan that runs to submission for their chosen programmes, with every failure logged and fixed (Slice 9 gate).
2. Every outside fact shown to a student carries its official source and a confirmed/unconfirmed label.
3. No task is lost or duplicated when workers crash (Spike 3 gate holds in production).
4. AI cost stays within $5 per student per year.
5. The OS runs with the PAI Counsellor switched off, and connects to it through three ports when it is on.

**Constraints stated by the owner.** Developers work mostly through Claude; no ongoing operations team; no domain expert on staff; student documents may be sent to the AI provider with consent; the student submits applications (no portal automation); statements are co-written; low budget; open source wherever it saves cost and time without lowering quality; no plan that breaks halfway through implementation.

**Team.** Two developers (the owner and one other), both working through Claude. Both are reviewers (each reviews the other's pull requests; nobody merges their own), both own the playbook and programme list, both collect test documents.

**Assumptions (correct if wrong).** One shared AWS host today; Counsellor and OS teams are separate; both OS developers work on the OS close to full time; target intake not yet named.

---

## 2. Scope

**In v1:** the route above; self-serve start; research of ~30 programmes; document reading and confirmation; grade, eligibility and funds checks; co-written statement of purpose and letters; application pack per programme; visa file; reminders; replanning; support inbox; Counsellor connection (Slice 8).

**Out of v1:** other levels (FSc/A-levels → bachelor's, PhD), other countries, local routes (Pakistan → Pakistan), scholarships beyond listing, portal automation, partner agents (A2A/MCP), WhatsApp, **automatic reading of university email** (decision D2 below).

**Scaling rule.** Countries and levels are data, not code: a route is a playbook, a document type is a field list, research runs per programme, the RouteContract carries origin, destination and level as fields. Add one direction at a time. Two fake routes stay in the test suite from Slice 1 to prove nothing is hardcoded: Pakistan → Ireland master's (two steps) and Pakistan → Pakistan BS (entry test, merit-list round, no visa) (decision D5).

---

## 3. Architecture

Six layers. Rule-based code wherever there is one right answer; AI only where judgement or language is needed.

| Layer | Components |
|---|---|
| 1 Ways in | Student app (Next.js), self-serve route builder, Counsellor adapter (Slice 8). All produce one **RouteContract**. |
| 2 Planning | **Playbooks** (versioned YAML route templates), **Plan compiler**, **Knowledge** (sourced facts) |
| 3 Control | **Kernel** (sole writer of plan state), **Scheduler / deadline engine**, **Rules + Supervisor** |
| 4 Work | **Task runner** (DBOS), **rule-based workers**, **AI agents** (Pydantic AI), **tool gateway** |
| 5 Student | **Inbox** (provide / approve / act / choose), notifications (app + email), support inbox |
| 6 Data | PostgreSQL 16 (`os` schema + DBOS system DB), S3, audit and cost log |

### 3.1 Invariants (go into `app/os/CLAUDE.md`, each with a check)

1. Only the kernel changes task status or plan structure. *(kernel-write test)*
2. Every task has exactly one owner, a registered module. *(registry check at startup and in CI)*
3. Every outside fact cites a Knowledge row with source URL, quote, check date and status.
4. Agents propose profile changes; the student confirms them.
5. Nothing leaves on the student's behalf without an approval bound to that exact artifact version (SHA-256 of the approved source).
6. No agent holds submit, payment or credential tools.
7. **Retries:** network/service retries happen only as DBOS step retries; answer-repair happens only through Pydantic AI output validation, max 2 attempts. No other retry code. *(resolves review F5)*
8. **Side effects are idempotent.** A DBOS step can run again if the worker crashed before its result was saved, so every external effect (email, file write, any outbound call that changes something) carries an idempotency key and is recorded in `os_outbox`; a repeated send with the same key is skipped.
9. Readers (see outside content) can't act; actors never see raw outside content.
10. A running plan pins its playbook version; upgrades are explicit plan revisions (see 4.3).
11. The OS imports only its own code and ports, never old-OS or Counsellor internals. *(Tach)*
12. Nothing country-specific in code: country names, currencies, grade scales, document types and attestation bodies live in playbooks or document configs. *(red-flag search + fake routes)*
13. All dates are stored timezone-aware with their source timezone; deadlines are end-of-day in the institution's timezone unless the source says otherwise.

### 3.2 Components

**RouteContract (Pydantic, versioned).** Student reference, origin, destination, level, ordered programme choices, target intake, source (`self_serve` | `counsellor`), external ref. Intake validates it, rejects with a reason, dedupes on (source, external ref, version). A changed route creates a plan revision, never a second plan.

**Playbooks.** YAML in the repo, validated at startup. Each task: `template_key`, `task_type`, `depends_on` (hard/soft), `lead_time_ref`, `condition`, `fan_out` (per programme), `fallback` (owner if module off), `protected`. Germany master's playbook drafted by a developer from official sources; every step cites its source; the reviewer checks citations (Spike 5).

**Knowledge.** Programme list and requirement facts: deadline(s), application route (uni-assist / VPD / direct), fees, language requirement, grade requirement and the inputs needed for grade conversion, required documents, intake. Each fact: value, exact quote, URL, checked-at, intake year, status (`confirmed` | `unconfirmed` | `stale`).

**Plan compiler (no AI).** Load pinned playbook → filter by conditions → fan out per programme → resolve lead times and deadlines from Knowledge (unconfirmed facts become research tasks or student questions) → build dependency graph, reject cycles → schedule backwards from hard deadlines → critical path and slack per task.

**Kernel.** Task states: `pending`, `ready`, `running`, `waiting_student`, `waiting_review`, `done`, `failed`, `skipped`, `cancelled` (+ `blocked` with reason). Applies results and validated operations; records each change as a numbered revision with its cause; writes events in the same transaction.

**Enqueue / reconcile (the dual-write rule).** Kernel marks a task `ready` and inserts an `os_enqueue_requests` row in the same transaction → enqueuer sends to a DBOS queue with key `task_id:attempt` (duplicates ignored) → reconciler every 5 minutes repairs any mismatch in either direction.

**Task runner (DBOS Transact).** Each attempt is a short DBOS workflow of steps (load inputs → call agent/worker → validate → save result). Steps checkpoint to PostgreSQL; a crash resumes from the last completed step on the same application version; blue-green deploys let old workers drain.

**Rule-based workers.** Grade converter (modified Bavarian formula; result always labelled *estimated*, inputs and sources shown, never blocks an application — review F9), deadline engine (hourly + on change; raises `slack_low`), funds calculator, checklist validator, renderer (PDF/DOCX), freshness sweeper (daily; deadline facts re-checked 30 and 7 days before).

**Agent harness (Pydantic AI).** Each agent is a YAML spec: id, version, zone (reader/actor), model tier (`cheap` | `strong`), allowed tools, output type, limits (steps, spend, timeout), validators, profile scopes, side-effect level. Model router maps tiers to providers with fallback: `cheap` → DeepSeek `deepseek-flash`, `strong` → `deepseek-v4-pro`, fallback → OpenAI project with a monthly cap. Model names live in settings.

**Tool gateway.** Per-spec allowlist, argument validation, idempotency key, per-domain rate limits, robots.txt respected (review F14), untrusted content fenced, spend charged, audit row written. No submit/pay/login tools exist.

**Agents (v1).**

| Agent | Zone | Model | May change | Checked by |
|---|---|---|---|---|
| Research | reader | flash | Knowledge facts as `unconfirmed` | 3 trust checks; Spike 1 answer key |
| Documents | reader | flash (vision) | profile proposals | student confirmation; Spike 2 set |
| Writer | actor | v4-pro | new draft versions | Critic, student approval |
| Critic | actor | v4-pro | nothing | student-rated samples |
| Pack generator | actor | flash | draft pack | checklist validator, student approval |
| Compliance | actor | flash | visa/funds file assembly | checklist validator, student approval |
| Supervisor | actor | v4-pro | typed proposals | kernel validation, student acceptance |

The Mail reader agent is **not** in v1 (D2). Students report university replies through inbox items ("Did X reply? Upload the letter"); the Documents agent reads uploaded letters.

**Research trust flow.** A fact is `confirmed` only if (1) it comes from an official source (university domain, uni-assist, DAAD, German mission), (2) two independent readings with different prompts agree, (3) it belongs to the target intake year. Otherwise it is shown as unconfirmed with the source link and a drafted email to admissions. Research and sweeps run outside DeepSeek peak hours where deadlines allow (review F15).

**Documents pipeline (review F1).** Upload (allowed types JPEG/PNG/WebP/PDF, size limit, processing only inside the worker container with timeouts — F13) → classify → text-based PDFs through Docling; scanned PDFs and photos rendered to images and **split into 2–4 tiles per page** before sending to `deepseek-flash` (DeepSeek downscales each image to about 1300×1300 px, max 1024 tokens per image, and accepts no PDFs) → extract fields per document-type config → cross-check across documents → student confirms every value. Images are sent inline; the DeepSeek Files API is not used, so no student files are stored at the provider. The OS checks consistency; it never claims a document is genuine.

**Co-written statements.** Interview (8–12 questions) → Writer drafts only from answers and confirmed profile → Critic scores against rubric and word limit (max 2 revisions) → student edits → student approves a specific version. Approval binds to the SHA-256 of the approved source text; the renderer is deterministic, so the rendered file is traceable to the approved version.

**Application pack.** Per programme: data sheet (every commonly asked field from confirmed profile), documents in required format and size, approved statement, checklist, and the programme's application route and fees. The student submits and pays.

**Inbox and notifications.** Kinds: provide, approve, act, choose. Reminders: >14 days slack weekly; 7–14 every 3 days; 2–7 daily; <48 h twice daily; zero → plan adjusted or escalated. Email via Resend through the outbox (invariant 8). Staging sends only to an allow-list.

**Rules and Supervisor.** Rules handle: rejection, deadline at risk, missing document, failed task, playbook upgrade. Supervisor proposes typed operations (add_task, skip_task, cancel_task, reprioritise, swap_programme, request_from_student, escalate) for other cases. Kernel checks: template exists, protected steps untouched, no dependent loses input, no other critical task pushed past deadline, swapped programme has confirmed facts. Limits: 10 operations per wake, 3 revisions per plan per day; beyond that, changes pause, the student is told, the case goes to the support inbox (review F7). Big changes need student acceptance.

**Events and modules.** `os_events` written in the state-change transaction, delivered via DBOS queues. Each agent/worker/adapter has a manifest (owns task types, needs, emits, fallback) and an on/off row in `os_modules`; disabling a module applies the playbook fallback.

**Ports (v1: three).** PlanSource (in), PlanQuery (in), EscalationSink (out). Standalone adapters first; Counsellor adapter in Slice 8 translates the Counsellor's decision record into a RouteContract. Profile, Documents and Knowledge are reached through Python interfaces in `app/os/ports/`, with tests that run on every pull request from either team.

---

## 4. Data and flows

### 4.1 Tables (`os` schema; all carry `tenant_id`)

`os_plans`, `os_tasks`, `os_task_edges`, `os_plan_revisions`, `os_playbook_pins`, `os_enqueue_requests`, `os_budgets`, `os_outcomes`, `os_task_attempts`, `os_agent_runs`, `os_human_tasks`, `os_approvals`, `os_artifacts`, `os_artifact_versions`, `os_events`, `os_modules`, `os_outbox` (idempotent external sends), spend/audit log. DBOS keeps its own system database (backed up). Knowledge, Profile and Documents tables are read through ports. Final column lists are fixed in the Slice 0 and Slice 1 specs.

### 4.2 Main flow

Route chosen → RouteContract → compiler → plan rows → kernel marks ready tasks → enqueue → DBOS attempt → worker/agent → result → kernel validates → next tasks / inbox items → reminders → student acts → … → outcome recorded.

### 4.3 Playbook upgrades on running plans (review G3)

Plans are pinned to a playbook version, but the pilot will find missing steps. A playbook upgrade is applied to running plans as a kernel revision: added tasks are inserted (with dependencies and dates recomputed), removed or changed tasks are only applied if not started; the student sees a "your plan was updated" note. Upgrades are explicit, logged and reversible.

### 4.4 Error handling

| Failure | Handling | Ends in |
|---|---|---|
| transient (service down) | DBOS step retry with backoff, max 3 | ready |
| invalid_output | Pydantic AI repair, max 2 | ready or failed |
| input_missing | inbox provide item | waiting_student |
| policy_blocked | approval item | waiting_review |
| budget_exceeded | stop; rules/Supervisor decide | failed |
| worker_crash | DBOS resume, same app version | running |
| module_disabled | playbook fallback | plan revision |
| external_rejection | rules: next programme / alternatives | plan revision |
| requirement_changed | recompute dates and slack; review | plan revision |
| route_invalid | student told with alternatives; support inbox (later Counsellor) | plan paused |

---

## 5. Testing and quality

- **Spec → plan → TDD per component.** Each slice gets its own spec and implementation plan (superpowers: brainstorming → writing-plans → test-driven-development → requesting-code-review → verification-before-completion). Acceptance tests are written from the spec and reviewed before implementation.
- **Fitness checks in CI:** Tach boundaries, kernel-write test, registry validation, migration-head check, standalone suite (Counsellor off), fake-route tests, contract tests (Slice 8).
- **Quality sets kept forever:** Spike 1 answer key, Spike 2 document set, Spike 4 rated drafts — re-run on any change to prompts, models or specs (Pydantic Evals).
- **Chaos run** (Spike 3, then nightly on staging): random worker kills, zero lost or duplicated tasks.
- **Reviewer guide** for every pull request, plus a backup reviewer (review F11).

### Validation spikes (pass marks set in advance)

| # | Spike | Pass mark | If it fails | Before |
|---|---|---|---|---|
| 1 | Research on 30 programmes | ≥95% of confirmed facts correct; ≥70% reach confirmed | more shown unconfirmed; fewer programmes | Slice 2 |
| 2 | Real documents (whole page vs tiled) | ≥90% fields correct; every cross-document mismatch caught | self-hosted OCR, or students type key values | Slice 3 |
| 3 | DBOS + Pydantic AI + DeepSeek | 100 crash runs: 0 lost, 0 duplicated; ≥99% valid outputs | fix before agent work | in Slice 0 |
| 4 | Co-written statements, 10 students | ≥8/10 usable after one edit; no invented facts | change questions or model | Slice 5 |
| 5 | Playbook walkthrough | before Slice 1: every step cites an official page, checked by the reviewer; during the pilot: students confirm nothing is missing (gaps applied via 4.3) | revise until it passes | Slice 1 |
| 6 | Cost on staging | ≤$5 per student per year | cheaper tier for more tasks | pilot |

---

## 6. Decomposition (each is its own spec → plan → build cycle)

| Slice | Builds | Done when |
|---|---|---|
| 0 Foundations | RouteContract, CLAUDE.md (root + `app/os`), Tach, CI, `app/os` skeleton, old-OS inventory; Spike 3 | Spike 3 passes; CI blocks a deliberate rule break |
| 1 Plan with no AI | kernel, states, scheduler, enqueue/reconcile, inbox, outbox, Germany playbook, compiler, workers, playbook-upgrade revision, fake routes | correct dated plan + inbox for a test student; crash loses nothing; fake routes run unchanged |
| 2 Knowledge | Research agent + trust rules, Docling, source/status display | Spike 1 holds |
| 3 Documents | tiled pipeline, extraction, cross-checks, confirmation | Spike 2 holds; new doc type by config only |
| 4 Self-serve start | route builder | student starts without the Counsellor |
| 5 Statements | interview, Writer, Critic, editor, version approval | Spike 4 holds |
| 6 Pack + visa file | pack generator, Compliance, checklists, renderer | test student's pack and visa file complete |
| 7 Replanning | rules, Supervisor proposals, acceptance | every scripted event → right change |
| 8 Counsellor | adapter, summary, escalation, frozen contract, contract tests | both teams' tests pass; standalone still passes |
| 9 Pilot | 10–20 students, one intake | all plans reach submission; failures fixed |

Every slice spec includes its student screens (mobile-first, since most students will use phones) and a simple wireframe (review F4).

---

## 7. Code location and team process

Same `Pai-C` repository, new `backend/app/os/`. Old OS frozen, inventoried in Slice 0, switched off feature by feature, deleted after the pilot. OS tables in `os` schema; OS models/settings/migrations in their own files with an Alembic branch label; own worker container; screens behind a switch. Two teams: short-lived branches off `dev`, CODEOWNERS (shared files need both teams), migration-head CI check, ports tests on every PR, weekly lead sync, same branch protection for both teams (needs Counsellor lead's agreement).

---

## 8. Technology

Existing: Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, Next.js, Docker + Caddy on AWS, S3, Resend, Supabase auth, Brave/Tavily search. New: DBOS Transact, Pydantic AI, DeepSeek (`deepseek-flash`, `deepseek-v4-pro`), OpenAI fallback, Docling, Crawl4AI, Tach, Pydantic Evals, Phoenix (self-hosted). Rejected: LangGraph, CrewAI/AG2, Temporal, Hatchet, OpenAI Agents SDK, DeepSeek Harness, portal automation, GPU OCR (unless Spike 2 fails).

---

## 9. Cost

DeepSeek official prices (verified 2026-10-12), per 1M tokens at peak: flash $0.30 in / $1.20 out; v4-pro $1.32 in / $3.96 out; off-peak 50%. Estimate ≈ $1.50 per student per year (≈$3 with 2× margin) + ≈$75/year research for 30 programmes. Ceiling $5 per student, alert at $4. Setup: DeepSeek prepaid $10–20, OpenAI fallback cap ~$20/month, S3 backups, Claude seats, possible staging server and managed database.

---

## 10. Security and privacy

Readers/actors split; per-spec tool allowlists; no submit/pay/login tools; approvals bound to hashes; minimum profile scopes per agent; secrets in Parameter Store; per-environment keys; images inline (no provider file storage); self-hosted tracing with retention; consent at upload naming the AI provider and data location; deletion on request; student terms reviewed by someone qualified before the pilot.

---

## 11. Decisions

| # | Decision | Status |
|---|---|---|
| D1 | Scope, architecture, technology, same repository | Agreed |
| D2 | No automatic university-email reading in v1; students report replies via inbox | **Default chosen — confirm** |
| D3 | Pilot intake chosen after team size is known; if Slice 8 misses the intake's application window, the pilot moves to the next intake | **Default chosen — confirm** |
| D4 | Documents split into tiles before vision reading | Default chosen (technical) |
| D5 | Fake local route added to Slice 1 tests | **Default chosen — confirm** |
| D6 | Playbook upgrades applied to running plans as revisions | Default chosen (technical) |

**Inputs:** team = 2 developers who review each other's work and share playbook, programme-list and document-collection ownership (2026-10-12). Still needed before Slice 0: the Counsellor lead's agreement to repository rules.
