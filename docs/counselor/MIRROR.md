# Counselor Mirror

Discovery can request a Mirror only when the saved Notebook is ready. The
`counselor.mirror` worker job is idempotent per Notebook version; a partial unique
index allows only one pending/running Mirror per workspace. It shares the
nonblocking workspace lock with the Analyst and retries through the existing job
runner. A stale Notebook version cannot publish a Mirror.

The existing pre-Mirror checker examines the whole Notebook in one batch. A
removal clears readiness and resumes discovery; checker errors fail closed.
Generation uses `PAI_MIRROR_MODEL` (defaults to `PAI_COUNSELOR_MODEL`), the runtime
Mirror prompt and the shared profile/Notebook/memory/language context. No model
call holds the application session's read transaction open.

Validation requires the nine fixed dimensions with evidence or `unknown:true`,
four or five unique lane keys, the configured script policy and one spoken
confirmation question. Numeric currency, percentage and score patterns are
rejected in opinion/blockers. This generic numeric guard does not establish the
truth of arbitrary prose; the prompt also forbids external world facts.
One invalid generation permits one regeneration. Two failures leave discovery
unchanged and publish nothing. Private model output is never logged on failure.

The existing Journey draft stores the validated payload and its Notebook version.
Migration `098_counselor_mirror` adds `MIRROR` to the stage constraint and the job
index. No new table is required. Publication uses `posting.py` with
`message_type=counselor_mirror`; durable drafts and message metadata permit retry
without duplicate cards. Voice receives only intro, opinion and question; it
never reads evidence rows or the Profile automatically.

The existing summary endpoint exposes the current card. Versioned Confirm and
Edit endpoints reject stale drafts. Confirm records `confirmed`, moves to
`RESEARCHING` and creates one durable `counselor.mirror_research` handoff to
`research_gateway.request_research("roadmap_light", ...)`. The existing gateway
deduplicates research runs. Its current accepted-goal requirements remain; PR 7
will rebuild the research brief from Mirror/Notebook/Snapshot.

Edit marks `needs_changes`, moves to `DIRECTION`, and submits an authenticated
normal student event so the existing Counselor, Analyst and Vault hooks run.
The card uses the existing translation catalogue and scrolls within a bounded
height on small screens. The old goal-summary component is replaced.

Offline JSON example: `backend/tests/fixtures/mirror/valid.json`.
Tests inject fake models; real provider evaluation is not part of this change.
