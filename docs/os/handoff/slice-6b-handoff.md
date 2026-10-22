# PAI OS handoff: Slice 6b (the visa file) built (2026-10-23)

**A new session reads this file first, all of it.** It continues `slice-6a-handoff.md`, which still holds the
environment, people, rules and earlier history. Where they disagree, this file is newer.

Authority order: parent spec > Slice 6b spec > Slice 6b plan > the rulings in the PRs > this handoff.
- **Slice 6b spec and plan:** `docs/superpowers/specs/2026-10-22-pai-os-slice-6b-design.md`,
  `docs/superpowers/plans/2026-10-22-pai-os-slice-6b.md` (both merged in #123).

## 1. Where things stand

Slice 6b is built, reviewed and fixed, in **seven PRs, each targeting `pai-os`**. They form a chain, so merge them in
order. After each squash merge, rebase the next branch with `git rebase --onto origin/pai-os <old base> <branch>` and
push with `--force-with-lease`.

| Order | Branch | What |
|---|---|---|
| 1 | `os/s6b-t1-doctypes` | Three document types by YAML: admission letter, blocked-account confirmation, insurance |
| 2 | `os/s6b-t2-funds` | `germany_master.visa.yaml`, the `funds` config section, the funds calculator, the proof check |
| 3 | `os/s6b-t3-plan` | The `review_visa_file` playbook task (plan Task 4, built before Task 3) |
| 4 | `os/s6b-t4-kind` | The second kind: `os_0011`, `os_visa_choices`, kind through inputs, workflow and approval |
| 5 | `os/s6b-t5-api` | `/v1/os/visa` |
| 6 | `os/s6b-t6-screens` | `/<workspace>/os-visa`, and the inbox's admitted / not admitted buttons. **`frontend/lib/api.ts` is shared: it needs a Counsellor review.** |
| 7 | `os/s6b-t7-gate` | The gate, the visa crash test and this handoff |

- **Never open or prepare a `pai-os` → `dev` PR.** The owners merge once, at the very end of all slices.

On the tip `os/s6b-t7-gate`:
- `pytest tests/os`: **968 passed**, 6 failed. The 6 failures on native Windows are the `SIGKILL` crash tests (including the new
  `test_crash_during_visa_build`) and `test_worker_enqueues_by_itself`. Linux CI runs them.
- Legacy suite: **1006 passed**, 3 pre-existing skips.
- Frontend: Vitest **109 passed**, `tsc` clean, and the OS-enabled build passes.
- Alembic head **`os_0011`**.

### What Slice 6b built (no AI)
- **Route config:** `app/os/packs/<route>.visa.yaml`. It uses the pack schema plus `funds`:
  - the route fact holding a year's amount;
  - the months;
  - the currency label (YAML only);
  - the accepted alternatives;
  - the proof item and field.

  It is validated at startup. Only Germany has one, so the fake routes have no visa page (`404`).
- **Funds:** `funds.py`. Required = `max(0, base × months / 12 − reduction)`.
  - The proof document's amount is compared as a number, so "11,904.00" and "11.904,00" both work.
  - A missing fact means "not confirmed yet", and the proof item stays `needs_action`.
- **The second kind:** the same `os.pack` workflow, manifest, renderer and approval, with `kind="visa"`.
  - The workflow ID starts with `visa:`.
  - There is one visa artifact per student. The chosen programme, the reduction and the funds are part of its
    inputs, so a change rebuilds it.
  - Visa ticks and added items are stored under `:visa`, so they never touch a pack's.
- **Approval:** an approval counts only while its manifest matches the current inputs, for display and for
  completing the plan task. Approving completes `review_visa_file` through the kernel.
- **Choice and pre-select:** `os_visa_choices` holds one row per student. The page pre-selects the programme whose
  `admission_result` task was completed with `{"choice": "admitted"}`. The inbox now offers "Admitted" and
  "Not admitted" buttons for that task.
- **Plan:** `review_visa_file` on Germany comes after `blocked_account` and `travel_insurance` and before
  `visa_apply`. The fake playbooks are unchanged.
- **API:** `/v1/os/visa` with GET, `PUT /choice`, `POST /build`, `PUT /details`, `PUT /items`, `GET /files/{sha}`
  and `POST /approve`.
- **Screen:** `/<workspace>/os-visa`. It reuses `PackView` (new optional `noun` and `notice` props), adds the funds
  box and the programme choice, and says "You apply and pay yourself."

## 2. Rulings (binding unless the owners change them; each is in its PR)
- **No Compliance agent** (owners, Q1 = A). **The motivation letter is the approved SOP** (Q2 = A).
- **Plan Task 4 was built before Task 3**, because Task 3's test needs the task.
- **One visa artifact per student**, keyed without the programme. The programme lives in the inputs and the manifest.
- **Visa ticks are stored under `:visa`.** **A visa file uses only the base SOP and CV, and ignores the programme's
  `required_documents`** (that list is the university's, not the embassy's).
- **`inputs_sha` adds `kind`, `programme` and `funds` only for a visa**, so 6a pack fingerprints and IDs are
  unchanged.
- **The API adds `PUT /visa/details` and `POST /visa/build`** beyond the spec's table (the details form and Rebuild).

## 3. Deferred minors (from the final review)
1. The funds fact's name is not checked at startup (`config.py`). A typo would show "not confirmed yet" for ever.
2. Visa uploads and visa details change every pack's `inputs_sha`, so open packs lose their approval. This is the
   6a design; the fix is a narrower pack fingerprint.
3. A huge reduction overflows `Numeric(14,2)` and returns `500`, not `422`. Fix: add `le=` on `ChoiceIn`.
4. The funds box shows no quote, and no link when the fact is missing.
5. `downloadOsVisaFile` duplicates the pack download helper in `api.ts`.
6. `os_visa_choices` and the `:visa` item rows are not deleted with a student.
7. `as_number` can merge digit runs in a free-text amount. It fails safe, as `needs_action`.
8. Concurrent builds for two programmes share the one visa artifact. It heals itself through the stale check.

## 4. Open items for the owners
- **Spec §11** (any questions still open there).
- **Reviewer's declined-to-judge items:**
  - whether a done `review_visa_file` should reopen when the programme changes later (the kernel has no reopen);
  - whether an unconfirmed funds amount should block approval (today it doesn't, per spec §6).
- Everything still open from `slice-6a-handoff.md` §3–4.

## 5. Next
Slice 6 is complete with 6a and 6b. The next slice is the owners' call. Keep the rule from memory: no `dev` merges
until Counsellor and OS are both fully built.

## 6. Environment notes (native Windows, this machine)
- Same as `slice-6a-handoff.md` §6.
- **Turbopack rejects a junctioned `node_modules`.** Run the OS-enabled build in a worktree with its own install.
  `/c/tmp/pai-t9` has one; use `git checkout --detach <branch>` there.
- **Stopping a background suite can leave its `pytest` process running on `os_test`.** Wait for it to exit before
  starting another full run, because two runs on one database corrupt each other.
