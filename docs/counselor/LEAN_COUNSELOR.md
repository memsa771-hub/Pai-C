# Lean Counselor discovery

The supplied `counselor_v3_3.md` is the runtime Counselor prompt. During discovery, factual questions are saved as `counselor_noted_questions` records with a workspace, source student event and open status. Old `ask_research` actions and question keys are accepted as deferred notes. They do not start Operator work. Replayed actions are idempotent per workspace and source event; questions are purged with private notes on workspace deletion.

`research_gateway.request_research` is the only Counselor module that directly delegates research. `roadmap_light` requires mirror confirmation. `stale_refresh` preserves refreshes of existing stale roadmaps, including a chosen route. `roadmap_deep` validates the chosen-roadmap scope but deliberately raises `NotImplementedError` until that later research step is built. PR 6 must set `journey.counselor_summary_draft.status` to `confirmed` when the student confirms the mirror. Discovery context contains no research section; after confirmation it contains existing roadmaps only. Opening an existing roadmap explicitly supplies that workspace-scoped artifact to the same deep turn for discussion.

The Analyst makes one call and validates its notebook without a sensitivity model call. PR 6 must await `check_notebook_before_mirror(workspace_id)` before generating a mirror and use the returned snapshot. This checks all free-text notebook entries in one batch. Flagged entries are removed, the write uses the checked version, and mirror readiness is cleared so gaps can be explored again. A concurrent update, failed check or unusable cleaned notebook raises and must block mirror generation. Checked content and student text are never logged; removals log path and reason. Per-call token logs remain available for the Counselor, Analyst and pre-mirror checker.

## Memory cadence decision

Per the task's explicit fallback, extraction remains **per turn**. `memory.turn_hook.enqueue_turn_extraction` accepts one user event and assistant event; `memory.extraction_context.TurnContext` has one `user_event_id` and `user_text`; `memory.extractor.build_user_prompt` treats earlier messages as context only and the current student message as the only evidence. It cannot accept a turn range without changing attribution and reconciliation. Queuing only every fifth turn would therefore lose four turns of evidence.

The extractor was not refactored. No inactive cadence or idle-session configuration was added: `PAI_MEMORY_EXTRACT_EVERY_N_TURNS` and `PAI_SESSION_IDLE_MINUTES` are not implemented in this fallback. Every completed human turn still queues its existing idempotent extraction job. An idle flush is unnecessary because no turns are buffered.

## Calls per normal successful human turn

Before Lean: one Counselor + one Analyst + one batched sensitivity check when entries change + one memory extractor = typically **4** calls. After Lean: one Counselor + one Analyst + one memory extractor = **3** calls. The reply path still makes **1** call. A blocked-script retry adds at most one Counselor call; version conflicts can rerun the Analyst once; existing job retries and research/plugin calls are outside these normal-turn counts. The separate pre-mirror check makes one batch call when the notebook has text. Simulator and grader calls belong only to the evaluation harness.

Migration `097_counselor_noted_questions` adds the deferred-question table. It follows migration `096`; no existing tables are dropped. This step does not implement the Mirror job or answer noted questions yet; those remain PR 6 and PR 7/8 work.
