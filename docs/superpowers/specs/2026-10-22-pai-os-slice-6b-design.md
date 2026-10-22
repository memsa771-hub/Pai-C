# PAI OS Slice 6b: the visa file (design)

Date: 2026-10-22. Parent: `docs/superpowers/specs/2026-10-12-pai-os-design.md` (§3.2 funds calculator, checklist
validator, renderer, the Compliance agent; invariants 3, 4, 5, 8, 12; §6 Slice 6). Builds on Slice 6a (the
application pack) on `pai-os`. Owners' split: **6a the pack, then 6b the visa file** (2026-10-22).

**Goal.** For the programme the student was admitted to, one working page with:
- the visa checklist, with every file ready in the required format;
- the **funds calculation**, with its source;
- a data sheet for the visa application form;
- the steps of the embassy's process, each with its source.

The student approves one exact version. **There is no AI in this slice.** The student applies, books and pays
themselves; the OS never does (invariant 6).

**Done when:**
- the Germany test student builds and approves a complete visa file, and `review_visa_file` is done;
- the fake Ireland and Pakistan BS routes run unchanged (invariant 12).

## 1. Decisions

| # | Topic | Decision |
|---|---|---|
| S6b-D1 | No AI | **The Compliance agent is dropped from 6b**, as a deliberate change from the parent spec (owners, 2026-10-22; for all the owners to confirm, §11 Q1). The checklist, the funds and the file are rules. **What would justify adding it back:** reading unstructured, applicant-specific requirements (e.g. the Consular Services Portal's generated list). It would then be a tool-less actor whose output goes through the Slice 5 facts check and student approval. |
| S6b-D2 | Reuse 6a | The visa file is **the same machinery as the pack with a second kind**. 6a's config schema (data sheet, checklist, formats, instructions, fees), the checklist validator, the renderer, the manifest, the `os.pack` workflow and the approval rules all take the file kind (`pack` \| `visa`) as a parameter. Nothing is copied. |
| S6b-D3 | Config | `app/os/packs/<route>.visa.yaml`, the pack schema plus a `funds` section, validated at startup. The Germany config ships; the fake routes have none (S6b-D9). |
| S6b-D4 | Funds calculator | **Rule-based and pure.** Required = the route's funds fact × `months` ÷ 12, minus the amount the student enters from a scholarship or other proof, never below 0. The YAML names the fact (Germany: the route fact `blocked_account_yearly_eur`), the months (12), the currency label and the accepted alternatives. The result shows the fact's quote, URL and status, and an `unconfirmed` amount is said plainly (the amount is set per year; §11 Q2). Python holds no amount and no currency. |
| S6b-D5 | Motivation letter | **The student's approved base SOP, rendered as "Motivation letter"** (owners). It is bound by its SHA-256 like any statement, with the note: "The embassy may want a letter about your study plan in Germany; check your SOP covers it." No new statement kind (§11 Q3). |
| S6b-D6 | New document types | Added **by YAML only**, as Slice 3 promised: `admission_letter` (institution, programme, student name, start date, issue date), `blocked_account_confirmation` (provider, holder name, amount, monthly payout, issue date) and `insurance_certificate` (insurer, holder name, cover start, cover end). The existing Documents reader reads them. Their holder names join the name cross-checks. |
| S6b-D7 | Checklist ↔ funds | The `blocked_account_confirmation` item is `needs_action` ("the amount is below what you need: X") when its confirmed `amount` is below the calculated requirement. The link is configured: the funds section names the item and the field that proves the amount. |
| S6b-D8 | Which programme | The visa file is for **one programme the student chooses** from their plan. The page pre-selects the one whose `admission_result` task says admitted, if any. The choice and the entered alternative amount are stored per student. |
| S6b-D9 | Plan | **A new Germany task, `review_visa_file`** (student, `approve`, not fanned out), after `blocked_account` and `travel_insurance` and before `visa_apply`. The visa file's approval completes it through the kernel. **The fake routes' playbooks stay unchanged** (6a lesson: they are shared Slice 1 fixtures). The visa step is route data; a route without a visa config has no visa page. |
| S6b-D10 | The embassy's own list | The embassy's portal generates the final document list per applicant, so the Germany checklist is **a route default to check against the portal**. The screen says so, and the student can add items as in 6a. |
| S6b-D11 | Out of scope | `visa_target_date` (still supplied by an admin), booking the appointment, paying the fee, buying insurance, and checking that a document is genuine. |

## 2. Components (`app/os/packs/`, extended)

- **`config.py`:**
  - `PackConfig` gains an optional `funds: Funds`, with fields `fact`, `months`, `currency_label`,
    `alternatives: list[{key, label}]`, `proof_item` (a checklist item key) and `proof_field` (a document field,
    e.g. `amount`).
  - `load_pack_configs(dir, kind="pack" | "visa")` reads `<route>.yaml` or `<route>.visa.yaml`.
  - `check_pack_config` checks `funds` too: the fact exists for the route, `proof_item` is a document item, and
    `proof_field` is a field of that document type.
- **`funds.py`:** `required(funds, fact, entered_reduction) -> FundsResult(required, base, months, reduction,
  currency_label, fact_status, quote, url)`. It is pure. A missing fact gives `required=None` with the status
  `missing`.
- **`checklist.py`:** takes an optional `FundsResult`. The proof item is `needs_action` when the proof document's
  amount is below `required`.
- **`inputs.py`:** `load_inputs(..., kind)`. For `visa`, it adds the route fact (`scope="route"`) and the student's
  stored choice and reduction.
- **`run.py`:** `os.pack(student, programme, route_key, year, kind)`. The artifact kind is `kind`, the workflow ID
  carries the kind, and everything else is unchanged. The data sheet and statements render as in 6a.
- **`approval.py`:** `REVIEW_TASK` per kind: `review_pack` for `pack`, `review_visa_file` for `visa`. The visa task
  is not fanned out, so it is matched by plan, not by programme.
- **`visa.py`:** `VisaChoiceStore`: `get(student)`, `set_programme(student, ref)`, `set_reduction(student, amount)`.

## 3. Tables (Alembic `os` branch, `os_0011`; every table has `tenant_id`)

- **`os_artifacts.kind`** gains `visa`.
- **`os_visa_choices`:** `student_ref`, `programme_ref`, `reduction` (numeric, ≥ 0), `updated_at`. Unique on
  (tenant, student).
- Rendered files reuse `os_pack_files`.

## 4. API (under `/v1/os/visa`; the student's own data only; writes need write access)

| Method and path | Purpose |
|---|---|
| `GET /` | The chosen (or pre-selected) programme, the funds result, and the visa file (status, checklist, data sheet, steps, fees, files, version, approval), shaped like `PackOut` |
| `PUT /choice` | `{programme_ref?, reduction?}`; a programme not in the plan, or a negative amount, is `422` |
| `PUT /items` | Tick, untick or add items, as in 6a |
| `GET /files/{sha256}` | Download one rendered file; another student's is `404` |
| `POST /approve` | `{sha256}`; `409` when stale, incomplete or no programme is chosen |

## 5. Student screen (mobile-first, 360 px; behind `NEXT_PUBLIC_OS_ENABLED`)

`/<workspace>/os-visa`:

```
┌ Your visa file ───────────────────┐
│ For: Uni Sample · MSc AI [Change] │
│ Funds you need: 11904 (EUR)       │
│  ⚠ unconfirmed for 2027 [source]  │
│  Scholarship/other proof: [  0 ]  │
│ Checklist (check it against the   │
│ embassy portal's own list)        │
│ ✓ Admission letter  [Download]    │
│ ⚠ Blocked account: amount below   │
│ ☐ Paid the visa fee               │
│ Data sheet …   Steps …            │
│ [Approve visa file]               │
└───────────────────────────────────┘
```

The page says plainly: "You apply and pay yourself. We never send anything for you."

## 6. Error handling

As 6a (a failed build shows `failed` with Rebuild; `building` while stale; a stale or incomplete approval is `409`),
plus:

| Failure | Handling |
|---|---|
| No programme chosen | The page asks for one; approve is `409` |
| The funds fact is missing | "Funds: not confirmed yet" with the research link; the proof item cannot be compared, so it is `needs_action` ("check the amount against the embassy's page") |
| The funds fact is unconfirmed | The amount is shown with "unconfirmed" and its source; it is still used |
| The proof amount is below the requirement | The proof item is `needs_action`, giving the shortfall |

## 7. Invariants touched

- **3:** the funds amount shows its fact's quote, URL and status. Every step has a source.
- **4:** amounts come from confirmed documents or the student's entry.
- **5:** approval is bound to the visa manifest's SHA-256.
- **6:** no submit, book or pay tool.
- **7, 8:** as 6a.
- **12:** the funds fact, months, currency label, checklist and document types are YAML. The fake routes are
  unchanged.

## 8. Testing (TDD; the pre-push checks as before, on every branch)

1. **Document types:** the three load; a reading model is built; the cross-check names include the holder names.
2. **Config:** the Germany visa config loads. An unknown funds fact, proof item or proof field stops startup.
3. **Funds:** the base amount, months, a reduction, the floor at 0, missing and unconfirmed facts, and no hard-coded
   currency.
4. **Checklist:** proof below or above the requirement; the SOP rendered as the motivation letter.
5. **Workflow:** `kind="visa"` builds its own artifact with no clash with the packs; replay is idempotent.
6. **Approval:** `review_visa_file` completes through the kernel; stale or incomplete is `409`.
7. **API:** choice validation, the student's own data only, and per-student downloads.
8. **Gate (`test_slice6b_gate.py`):** a Germany test student goes from documents, approved statements, a chosen
   programme and the funds to an approved visa file, and `review_visa_file` is done. The fake routes have no visa
   page and still pass their gates.
9. **Screens (Vitest):** the funds box (amount, status, source), the choice, checklist marks, Approve only when
   ready, the "you apply yourself" line, 360 px.
10. **Crash:** `kind="visa"` builds survive SIGKILL (Linux CI).

No billed run: there is no AI in this slice.

## 9. Done when

- §8 is green in CI on every PR.
- The gate passes.
- One fresh final review has been done, with its fix pass.

## 10. Build order (one PR per task, **each targeting `pai-os`**, merged in order; rebase the next after each merge)

1. The three document types.
2. Visa config, the funds calculator and their validation.
3. `os_0011`, the second kind through store, inputs, workflow and approval.
4. The `review_visa_file` playbook task.
5. API.
6. Screens (`api.ts` is shared: Counsellor reviewer).
7. Gate test, crash test, final review and fix pass, handoff.

## 11. Open questions for the owners

| # | Question | Proposal |
|---|---|---|
| Q1 | Confirm dropping the Compliance agent (S6b-D1) | Drop it; add it back only to read applicant-specific requirements |
| Q2 | The 2027 blocked-account amount | Re-check the embassy page for 2027 and confirm the route fact (it is 11,904 € for 2025, `unconfirmed`) |
| Q3 | Is the SOP acceptable as the visa motivation letter? | Yes for the pilot; revisit if the embassy rejects one |
