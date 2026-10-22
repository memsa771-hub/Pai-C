# PAI OS Slice 5: Statements (design)

Date: 2026-10-22. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§3 co-written statements, agents
table, invariants 4 and 5, §5 Spike 4, §6 Slice 5). Builds on Slices 0–4 on `pai-os`.

**Goal.** The student and the OS co-write a **statement of purpose** (SOP, also called a motivation letter) and a
**CV**.
- An interview collects the student's own material.
- A Writer drafts only from that and the student's confirmed profile.
- A Critic and a rule-based facts check catch weak or invented content.
- The student edits, then approves one exact version, bound by its SHA-256.

**Done when (parent §6):**
- **Spike 4 holds:** at least 8/10 drafts are usable after one edit, for each document kind, and **no invented
  facts**.
- An approved version is traceable by its hash.
- The plan's documents task completes on approval.
- The same code serves a second route with its own questions and rubric.

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| S5-D1 | Scope | **SOP and CV** (owners, 2026-10-22). Reference letters are a later slice: someone else writes them and the referee approves. Each kind has one **base** artifact per student, plus an optional **programme** SOP when the programme asks for its own. |
| S5-D2 | Statement rules | A new research field, **`statement_requirement`** (needed yes/no, word or character limit, prompt), researched and quoted like any fact. **Fallback:** the student pastes the programme's prompt and limit. Otherwise a **route default** applies, labelled as a default. |
| S5-D3 | Interview | **8–12 fixed questions per route, in config** (`statements/interview.<route>.yaml`), with id, prompt, hint and `required`. Answers are saved one at a time. **The Critic may ask up to 2 follow-up questions** when material is missing: *ask, never invent*. |
| S5-D4 | Agents | **`writer.v1` and `critic.v1`**: zone `actor`, tier `strong`, **no tools**, output retries at most 2, no tool retries (invariant 7). The Writer sees only the answers, the confirmed profile values its kind needs, and the rules. The Critic sees the draft, the same inputs and the rubric. Student text is fenced as data. |
| S5-D5 | Invented facts | **`facts_check` (no AI):** every number, date, name, institution and score in a draft must appear in the answers or the confirmed profile, compared after normalising. If not, the draft is flagged with the exact phrases. The Writer gets them back to remove or turn into a question. Flags never block the student's own edits. |
| S5-D6 | Loop | `os.statement` DBOS workflow: load → Writer → facts check → Critic → revise (at most **2** revisions) → store. Each model request is a DBOS step (`DBOSDurability`), and each reading is an `os_agent_runs` row. Workflow ID `statement:{tenant}:{artifact}:{inputs_sha16}`, so the same inputs are never drafted twice. |
| S5-D7 | Artifacts | Generic tables, reused by Slice 6: `os_artifacts`, `os_artifact_versions` (immutable text, SHA-256, author `writer` or `student`, critic report, flags) and `os_approvals` (artifact, version, SHA-256). A version is never changed in place. |
| S5-D8 | Approval (invariant 5) | The student approves one version. The approval stores that version's SHA-256. An edit after approval makes a new, unapproved version. The plan's documents task (named in the playbook, as in Slice 4) completes when every needed artifact has an approval. |
| S5-D9 | Limits | The Writer is told the limit. If a draft is still over it after 2 revisions, it is labelled "over by N words". It is never trimmed silently. |
| S5-D10 | Spend | Each draft or revision is an agent run. The monthly cap is `OS_STATEMENTS_MONTHLY_USD`, default 10. Over the cap, drafting waits with a `budget_exceeded` event. A draft costs about $0.05–0.15 on the strong tier. |
| S5-D11 | Spike 4 | **Role-played set:** the owners and colleagues play about 10 students, and two people judge each SOP and CV ("usable after one edit", yes/no, and mark invented facts). It stays outside the repo, like the Spike 2 documents. **Fictional set (in the repo):** 10 personas with planted traps, checked automatically. |
| S5-D12 | Route-neutral | Questions, rubric, default limit and the documents task are route config. Python knows only `sop` and `cv` as generic kinds, with their profile scopes in config. |

## 2. Components (`app/os/`)

| Unit | Responsibility |
|---|---|
| `statements/config.py` + YAML | Loads, per route, the interview questions, the rubric per kind, the default limit, the documents task, and the profile keys each kind may use. An unknown key fails at startup. |
| `statements/facts_check.py` | `claims(text) -> list[Claim]` (numbers, dates, capitalised names and institutions, scores); `unsupported(claims, sources) -> list[Claim]`, after normalising case, punctuation, number formats and date formats. Pure. |
| `artifacts/store.py` | `ArtifactStore`: create or get an artifact; add a version (computes the SHA-256; never updates); list versions; approve (version and hash); the current approval; delete for a student. Every query filters by tenant. |
| `agents/writer.v1.yaml`, `agents/critic.v1.yaml`; `statements/agents.py` | Builds both tool-less agents. Their outputs are `Draft(text, used_sources)` and `Review(scores, fixes, follow_ups ≤ 2, ok)`. |
| `statements/run.py` | The `os.statement` workflow, enqueueing, and the budget. |
| `statements/interview.py` | Saves answers, answers to follow-up questions, and the student's pasted rules. |
| Research profile | Adds `statement_requirement` (type `statement_rule`: needed, limit_words, limit_chars, prompt). |
| API + screens | §4 and §5. |

## 3. Tables (Alembic `os` branch, `os_0008`; every table has `tenant_id`)

- `os_statement_answers`: student, question id, answer, updated at. Follow-up answers live here too, with their
  question text.
- `os_artifacts`: student, kind (`sop`/`cv`), programme ref or null for the base, status (`empty`, `drafting`,
  `draft`, `failed`, `approved`), current version.
- `os_artifact_versions`: artifact, number, text, SHA-256, author, critic report (JSONB), flags (JSONB), word count,
  limit used, created at. Unique on (artifact, number).
- `os_approvals`: artifact, version, SHA-256, approved at. One current approval per artifact.
- `os_agent_runs` gains an `artifact_id` (nullable), like `document_id`.

## 4. API (under `/v1/os`; the student's own data only; writes need write access)

| Method and path | Purpose |
|---|---|
| `GET /statements/interview` | The route's questions with the student's answers and any follow-up questions |
| `PUT /statements/answers/{question_id}` | Save one answer |
| `GET /statements` | The student's artifacts with their latest version, flags, critic notes, limit and approval |
| `POST /statements/{kind}/draft` (`{programme_ref?}`) | Start a draft. `409` if required answers are missing (names them); `202` with the artifact |
| `PUT /statements/{artifact_id}/text` | Save the student's edit as a new version (facts check runs; flags returned) |
| `POST /statements/{artifact_id}/approve` (`{version}`) | Approve that version; returns its SHA-256 |
| `PUT /statements/rules/{programme_ref}` | The student's pasted prompt and limit (fallback) |

## 5. Student screens (mobile-first, 360 px)

- **Interview:** one question per card, with a hint, saved as the student types, and a progress count. Follow-up
  questions appear at the top when the Critic asks.
- **Draft:**
  - the text in an editor, with the limit and the count ("812 / 1,000 words");
  - flagged phrases highlighted with "we could not find this in your answers or profile";
  - the Critic's notes as a short list;
  - **Save**, **Write again**, **Approve this version**.
- **Approved:** the version number, the date, a short hash, and a "this is the text that goes in your application"
  note.

## 6. Error handling

- A required answer missing gives `409`, naming the questions. Missing profile values are left out and listed,
  never guessed.
- **Flags:**
  - After 2 revisions, flagged claims stay highlighted, and the draft is marked "check these".
  - The system never marks a flagged draft ready.
  - The student may approve after reading the flags (their words).
- A failed agent run gives artifact status `failed` with **Write again**; DBOS step retries come first.
- Over budget: waits, with `budget_exceeded`.
- Answers and drafts are student data: tenant-filtered, never logged, and deleted on request. Student text is fenced
  as data, and the agents have no tools.

## 7. Invariants touched

- **4** (agents propose, students confirm): only the student approves.
- **5:** an approval binds a hash.
- **6/9:** no tools for agents that see student text.
- **7:** retry rules.
- **12:** questions, rubrics and limits are route config.
- **The kernel as sole writer:** the documents task is completed through the kernel.

## 8. Testing (TDD; the pre-push checks as before)

1. `facts_check`: numbers, dates (formats), names, institutions, scores; supported against answers and against the
   profile; phrasing variants.
2. Config: loading, unknown keys refused, a second route with other questions.
3. `ArtifactStore`: versions are immutable, the SHA-256 is right, approval binds the hash, an edit after approval
   unbinds it, tenant isolation.
4. Workflow with fake models:
   - at most 2 revisions;
   - follow-up questions instead of guesses;
   - flags passed back to the Writer;
   - the same inputs are never drafted twice;
   - a crash mid-draft resumes;
   - the budget.
5. API: the interview, the `409` for missing answers, drafting, an edit that runs the facts check, approval, only
   your own data, and the plan task completing on approval.
6. Screens (Vitest): the interview form, the editor count and limit, flags, approve, 360 px.
7. **Spike 4 runner** (`tests/os/quality/run_statement_quality.py`):
   - **offline on the fictional set:** every planted invention flagged, limits kept, no persona's facts in another's
     draft;
   - **billed** only with the owners' OK;
   - the role-played results are recorded in `docs/os/slice-5-quality-report.md` (rates and counts only).

## 9. Done when (the slice gate)

- §8 is green in CI (`os` and `legacy`).
- **Spike 4:** at least 8/10 usable after one edit for each of SOP and CV in the role-played set, 0 invented facts,
  and the fictional set passes all its automatic checks.
- No merge into `dev` at the slice gate (owners: one merge at the very end).

## 10. Build order (one branch and PR per task, off `pai-os`)

1. Route config: interview, rubric, kinds, limits, documents task.
2. `facts_check`.
3. Tables `os_0008` and `ArtifactStore`.
4. The `statement_requirement` research field and rule resolution (researched → pasted → default).
5. Writer and Critic agents.
6. The `os.statement` workflow and budget.
7. Interview, follow-ups and pasted rules.
8. The API and plan task completion.
9. Screens (`frontend/lib/api.ts` is shared: it needs a Counsellor reviewer).
10. The fictional set, the Spike 4 runner and the gate test.

## 11. Open questions for the owners

| # | Question | Proposal |
|---|---|---|
| Q1 | The default limit when nothing is found or pasted | SOP 1,000 words; CV 2 pages (about 700 words) |
| Q2 | The SOP's language | English only in Slice 5 |
| Q3 | Who judges Spike 4 | The student who role-played, plus one owner who didn't write the answers |
