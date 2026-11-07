# P2-T5 plan: the review queue (R-25, R-42, R-72 collection, R-75)

Spec: P2 §4.5, P2-D15, P2-D16, §6.1 row T5, owner rulings §11.2 (AI check 1 and AI check 2 may be the two checks).
Branch `pc/p2-t5-review-queue`, migration `os_0026_review_queue` (down_revision `os_0025`).

## Design in short
- `os_reviewers` (ref, name, role checker/approver/admin, kind person/ai, token sha256, active). Script
  `backend/scripts/os_reviewers.py` (add, disable, enable, rotate, list). Token header `X-OS-Reviewer-Token`.
- `os_review_items` (kind verify/report/change/suspect_domain/collect/conflict/import_dispute, status, fact link,
  dedupe key, batch_ref, payload), `os_fact_reviews` (one per reviewer per item; step check/approve/collect),
  `os_review_files` (evidence bytes, size cap from data), `os_review_attestations` (batch attestation, P2-D16).
- Policy as data: `knowledge/review_policy.yaml` (kinds allowed to count, owner ruling reference, evidence cap).
  People can replace the AI checks by editing data, not code.
- Independence: two different reviewer ids; a reviewer sees no other review on an item before submitting their own
  (server side); the author of a correction or collection cannot check it.
- `verified` transition through `SqlKnowledge.set_status` (cause `review`). High-stakes needs check+approve, other
  facts one check (§4.5). A machine/human-read `unconfirmed` fact becomes `confirmed` by the first positive check (R-72).
- `wrong` demotes to `unconfirmed` and revises plans (`after_fact_change`); `reject` after a positive check opens a
  `conflict` item; `unclear` opens a `collect` item.
- D-t1-2: a `fact_state` helper (`is_sourced(status)`); fix packs/inputs.py, packs/instructions.py, replan/apply.py,
  workers/freshness.py, store.mark_stale; research/run.py already uses `.confirmed` (test pins it).

## Tasks / files / tests
1. Trust-level fixes (store.py, freshness.py, apply.py, inputs.py, instructions.py) - tests `test_p2t5_verified_consumers.py`.
2. Migration + models + policy yaml + `knowledge/review/` (reviewers.py, queue.py, service.py, files.py) - tests
   `test_p2t5_review_store.py`, `test_p2t5_review_flow.py` (two-person, independence, collect, conflict, attest).
3. API `api/review.py` mounted in router - `test_p2t5_review_api.py`.
4. Script - `test_p2t5_reviewers_script.py`.
5. Frontend: `lib/os-review.ts`, `components/os/review-*.tsx`, page `os-admin/review`, vitest.
6. requirements yaml `built: true`, tests tagged with R-IDs; checks; report.
