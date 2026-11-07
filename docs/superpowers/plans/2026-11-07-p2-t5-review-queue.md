# P2-T5 plan: the review queue (R-25, R-42, R-72 collection, R-75)

Spec: P2 §4.5, P2-D15, P2-D16, §6.1 row T5, owner rulings §11.2 (AI check 1 and AI check 2 may be the two checks).
Branch `pc/p2-t5-review-queue`, migration `os_0026_review_queue` (down_revision `os_0025`). This file describes what was
built, after the review fixes.

## Design
- Tables: `os_reviewers` (ref, display name, **identity**, role checker/approver/admin, kind person/ai, token sha256, active),
  `os_review_items` (kind, status, resolution, fact link, dedupe key + join count, batch ref, payload),
  `os_fact_reviews` (one per reviewer per item; step check/approve/collect; fact digest; high-stakes need as of the review),
  `os_review_files` (evidence bytes), `os_review_attestations` (batch attestation, P2-D16).
- Policy as data: `knowledge/review/review_policy.yaml` (counting kinds, min persons, steps, evidence types and cap, the
  note on why only passive formats). The owner ruling is policy: remove `ai` to require people again.
- Independence: distinct reviewer ids and **distinct identities** (the person, or the model and prompt behind an AI ref);
  no reviewer, an admin too, sees another review or an uploader before giving their own or before the item closes; the admin
  audit endpoint is a separate view; the author of a correction or collection cannot check it.
- Trust: `verified` only through `set_status(cause="review", expected_digest=...)` on the locked row. High-stakes needs a check
  and an approval; others one check. A machine- or hand-read fact is made `confirmed` by the first positive check, and that
  check does not also count towards `verified`.
- Integrity: `SqlKnowledge._revise` voids a fact's open verify item in the same transaction when its reading (value, quote,
  URL, class, read method) changes (locked items are skipped; their reviews carry a digest and are voided when applied).
  `evaluate` runs in one transaction and can be run again.
- Evidence: the server decides the type from the bytes (`review/sniff.py`), allows only PDF, PNG, JPEG, WEBP and plain text;
  PDF and images are shown, everything else is a download; `Content-Disposition` carries an RFC 5987 name; the upload is
  refused early on `Content-Length`. The screen never opens a blob of an active type.
- D-t1-2: the `== "confirmed"` fixes are T1's; `knowledge/research/run.py` already uses `Fact.confirmed` (test pins it).

## Files
Backend: `alembic/versions_os/os_0026_review_queue.py`, `app/os/models.py` (tables), `app/os/knowledge/store.py` (`revise`,
`locked`, `fact_digest`, `StaleFact`, `conn=` on writes, voiding), `app/os/knowledge/review/{queue,reviewers,policy,sniff}.py`,
`review_policy.yaml`, `app/os/api/review.py` (+1 line in `router.py`), `scripts/os_reviewers.py`.
Frontend: `lib/os-review.ts`, `lib/api.ts` (reviewer calls), `components/os/review-item.tsx`,
`app/[workspaceId]/os-admin/review/page.tsx`, `components/os/visa-funds.tsx` (verified counts as confirmed).
Tests: `tests/os/test_p2t5_{verified_consumers,review_flow,review_api,reviewers_script,migration}.py`, `tests/os/test_models.py`
(table list), `lib/os-review.test.ts`, `components/os/review-item.test.tsx`.

## Verification (after the review fixes)
tests/os 2418 passed; legacy 2560 passed; vitest 590 passed; next build ok; tach, freeze, one alembic head, traceability ok.
