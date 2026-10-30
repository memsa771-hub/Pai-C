# PAI OS handoff: Slice 4 (Self-serve start and eligibility), done (2026-10-22)

**A new session reads this file first, all of it.** It continues `slice-3-handoff.md`, `slice-1-handoff.md` and
`README.md` in this folder, which still hold the general rules, people, environment and earlier history. Where they
disagree, this file is newer.

Authority order: parent spec > Slice 4 spec > Slice 4 plan > the rulings in §4 > this handoff.

- Parent spec: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (invariants §3.1, slices §6)
- **Slice 4 spec:** `docs/superpowers/specs/2026-10-21-pai-os-slice-4-design.md` (S4-D1…D11; API §4, screens §5)
- **Slice 4 plan:** `docs/superpowers/plans/2026-10-22-pai-os-slice-4.md`. **It is still only on branch
  `os/s4-spec` (PR #89, open)**; merge #89 to bring it into `pai-os`.
- OS rules: `backend/app/os/CLAUDE.md` (invariants) and the root `CLAUDE.md`

## 0. Start here

1. Set up as in `slice-3-handoff.md` §3, and run the checks (§3 below). Everything must be green with **0 skipped**.
2. Slice 4 is complete and merged. What comes next is **Slice 5: Statements** (§6), starting with brainstorming.
3. **Never open or prepare a `pai-os` → `dev` PR.** The owners merge `pai-os` into `dev` once, at the very end of
   all slices. The Slice 2 gate PR #66 stays closed.

## 1. Where things stand

- **Slices 0–3:** built and merged into `pai-os`.
  - The Slice 3 Spike 2 gate passed at the owners' pilot bar: ≥ 0.89, with tiles on the strong tier
    (`docs/os/slice-3-quality-report.md`).
- **Slice 4: done.**
  - All PRs are merged: #84 spec; #85–#95 Tasks 1–10; #96 the gate test; #97 the final-review fixes.
  - **Exception: #89 (the plan), open.**
  - On `pai-os` at `38f4c77`: `pytest tests/os` gives **778 passed, 0 skipped**; the legacy suite 1006 passed (3
    pre-existing skips); frontend Vitest 66 passed; `tsc` and the OS-enabled build pass.

### What Slice 4 built
- **Eligibility, route-neutral (invariant 12):**
  - `app/os/eligibility/`: `rules` (the playbook's `eligibility:` block), `methods` (`linear_scale`,
    `threshold`, `weighted_aggregate`), `evaluate` (a pure card per programme, on read), `swaps` (up to 3
    suggestions) and `notes` (one inbox note per verdict change).
  - Germany's modified Bavarian formula is `linear_scale` with Germany's numbers. The two fake routes (Ireland
    `threshold`, Pakistan BS `weighted_aggregate`) run the same code in the tests.
- **Self-serve start:**
  - `app/os/routes/builder.py`: `start`, `swap` and `remove`, only through `PlanService.change_programmes` and
    `Kernel.change_contract`.
  - At most 3 programme changes per plan per day. A second start with different choices gives `409`.
- **Programme requests:** `app/os/knowledge/requests.py`.
  - A request is researched once, then shared with every student.
  - Its facts stay **unconfirmed** until an admin sets the programme `active`.
  - At most 3 requests per student per day.
- **The minimum-passing-grade letter** is a document type added by config only. It replaces the provisional
  minimum pass when the letter's scale matches.
- **API:**
  - `/routes`, `/routes/{route}/programmes`, `/eligibility/{ref}`, `/plans/self`, `/plans/{id}/swap`,
    `DELETE /plans/{id}/programmes/{ref}`, `/programmes/requests`;
  - inbox `notes` and `/inbox/notes/{id}/read`;
  - `GET /programmes` carries `plan_id` and `rank`;
  - admin open facts lists requested programmes.
- **Screens:** `/<workspace>/os-start` (builder, eligibility card, request form), and inbox **Eligibility updates**
  with a confirmed **Swap**.
- **Migrations:** `os_0006` (requests, seen, notes; programme status `requested`) and `os_0007` (last-told verdicts
  per plan).

## 2. Lessons from this slice (process)

- **A squash merge drops commits pushed after the merge started.** This happened twice: #65 (Slice 2) and #94.
  #94's follow-up was re-landed in #96. After merging a PR that got a late commit, check that the commit's content
  is in `pai-os`.
- **A PR stacked on another needs a rebase after its base is squash-merged.** #97 conflicted until its own commit
  was replayed onto `pai-os` (`git rebase --onto origin/pai-os <old base tip> <branch>`) and force-pushed with a
  lease.
- **Check branches before deleting them:** by ancestry, by squash title, and file by file against `pai-os` history.
  That check found the unmerged plan (#89).
- **The fresh final reviewer earns its cost.** It found 1 Critical and 6 Important issues that the per-task tests
  missed. Each fix has a test that failed first (`tests/os/test_slice4_review_fixes.py`).
- **Frontend checks from WSL:** WSL has no Node. Copy `frontend/` to a Windows temp folder (without
  `node_modules`), run `npm ci`, `npx vitest run`, `npx tsc --noEmit` and `NEXT_PUBLIC_OS_ENABLED=true npm run
  build` there, then copy the changed files back into the repo.

## 3. Checks (expected now)

On `pai-os` at `38f4c77`:
- `tach check` ✅, one alembic head ✅;
- `pytest tests/os` **778 passed, 0 skipped**;
- legacy **1006 passed, 3 skipped**;
- frontend **66 passed**.

## 4. Rulings (Slice 4)

Binding unless the owners change them; each is also in its PR.
- **Plan:**
  - The migrations are `os_0006` and `os_0007` (`os_0005` was taken).
  - Notes use two tables: last verdict told, and the notes themselves. Cards are never stored.
  - The kernel gained `change_contract`.
  - The task the builder completes is named in the playbook (`self_serve.choose_task`).
- **Grades:**
  - Germany's rounding is `truncate`. **Unverified** against the KMK decision of 12.09.2013; it is one YAML value.
  - A minimum-pass letter only counts for a scale with the same best grade.
  - A value on another scale (e.g. a CGPA out of 5) skips that scale (`other_scale`).
  - An impossible scale or total gives `needs_input` (`invalid_value`), never an error.
  - The tolerance is 1e-9, so a value exactly at the requirement meets it.
- **Language and tests:**
  - A required test, a language level with no score, or a score with no document type to check it (TOEFL, PTE)
    gives `needs_input` (`no_proof_type`), never `likely_below` or `likely_meets`.
  - Nothing stated gives `unknown`.
- **Swaps:**
  - Only a `likely_below` line triggers suggestions, and a candidate must positively meet each failing check.
  - Swaps and removals share a limit of 3 per plan per day, on the database clock.
  - A swap re-applies the student's change to the plan's current programmes on every retry.
- **Notes:**
  - The verdicts are recorded at start and after a swap, so the first change notes.
  - Last-told verdicts are kept per plan.
  - `held` (values under an open document finding) is empty, because Slice 3 findings are only on names and dates
    of birth.
  - A failing note is logged and never breaks a confirm or fact storage.
- **Requests:**
  - https only; the host becomes the official domain; the ref is derived from the URL.
  - Requests carry an intake year, and research is asked for whenever that year has no facts (same workflow ID per
    day).
  - A programme being researched is shown only to its requester.
  - **A requested programme's facts stay unconfirmed until an admin reviews it.**
- **API and screens:**
  - Builder cards use the route's newest playbook; notes use the plan's pinned one.
  - `GET /routes` lists no intakes, and the start page's term is `winter`.
  - Swap and remove on a plan page are deferred; swaps happen from inbox notes.

## 5. Deferred minors (from the final review, #97)

1. The swap daily limit and "started" checks run outside the plan lock: concurrent swaps can exceed 3 a day.
2. The swap and remove endpoints let `CompileError`, `PlaybookError` and `StaleDraft` through as 500.
3. Deleting a document doesn't call the notes hook.
4. `on_fact_change` loads every plan of the tenant for the year on each call; filter with JSONB containment.
5. A few builder queries on `os_tasks` and `os_plan_revisions` lack a `tenant_id` filter. Ownership is checked
   first, so nothing leaks.
6. A requested ref comes from the URL only: the same URL on a second route returns the first route's ref.
7. The start page lets a student choose their own requested programme before it has facts. Starting then fails
   with a generic error.
8. Spec §6's "could not be researched yet" state is not shown to students. Admins see it in open facts.

## 6. What comes next: Slice 5, Statements

Parent spec §6: the **interview, Writer, Critic, editor, version approval**. It is done when **Spike 4 holds**:
co-written statements for 10 students, at least 8 of 10 usable after one edit, and **no invented facts**.
- It is the first slice where an agent writes for the student. Invariant 4 (agents propose, students confirm) and
  the no-invented-facts rule are central.
- **Spike 4 needs the owners:** 10 real students who agree to take part, and someone to judge "usable after one
  edit". Their material follows the same rules as the Spike 2 documents: outside the repo, never in chat or logs.
- Process: superpowers brainstorming → the Slice 5 spec → the plan → native execution with TDD → one fresh
  reviewer → one fix pass.

## 7. Open items for the owners

- [ ] Merge **#89** (the Slice 4 plan).
- [ ] Verify Germany's grade rounding (`truncate`) against uni-assist / the KMK decision; it is one YAML value.
- [ ] Review student-requested programmes (admin open facts) and set the good ones `active`. Their facts stay
  unconfirmed until then.
- [ ] Decide the 8 deferred minors (§5): one small PR, or later.
- [ ] Earlier items still open: Slice 3 spec §11 Q1–Q3; TU Chemnitz Automotive `application_route` hand-confirm
  (Slice 2); rotate the keys pasted into chat in earlier sessions.

## 8. Prompt for the next session

Set up first (`slice-3-handoff.md` §3). Then start `claude` in the repo root and paste:

> Continue PAI OS. Run `git fetch origin`, then read `docs/os/handoff/slice-4-handoff.md` from `pai-os`, all of it,
> and the files it names when you need them. Follow its working rules, including the secrets and personal-data
> rules, and never open or prepare a `pai-os` → `dev` PR. Run the §3 checks. Then tell me in a few lines where
> things stand, and start Slice 5 (Statements) with superpowers brainstorming: classify it, read the parent spec's
> Slice 5 parts, and ask me one question at a time.
