# Codex task: PAI Counselor v3 "deep" (in-depth personal counseling)

Repo: `memsa771-hub/Pai-C`. Base: `feature/counselor-complete`. Work branch: `feature/counselor-deep`. One PR per step into `feature/counselor-complete`. Never push to `dev` or `main`.

This task **replaces** `codex_prompt_counselor_simple.md`. If any simple-mode PRs are already merged, keep their mode flag, memory hook fix and context builder, and extend them.

## Scope of THIS build: up to roadmaps only (read first)

Build in this order. Do not start a later step before the earlier one's PR is merged.

1. **Phase A: the Counselor talks well.** Steps 1, 2, 3 and 4, plus the eval harness from step 7 with the first 6 personas. The eval must exist before any prompt tuning.
2. **Phase B: the mirror.** Step 5.
3. **Phase C: roadmaps.** Step 6a (knowledge base), then step 6.

Then step 11, the manual test.

Step 9 is limited for now. The engagement-style handling lives in the prompt only. Of the code changes, implement just these three:

- the `depth_mode` mirror gate;
- `mirror_confidence`;
- the `do_not_push` flag.

**Step 10 (coach mode) is DEFERRED.** Do not build it in this task. Anything that touches PAI OS is out of scope; the decision record is created by the existing Choose flow, unchanged.

## Product goal

PAI Counselor must counsel the way the best human counselor would.

1. Get to know the person before advising.
2. Depth-check every claim (when, how long, what exactly, what was hard, what happened after) to separate real, sustained interest from a passing spark.
3. Find where the wish comes from, and what each parent wants and why.
4. Test the stated goal against the real work and the student's life.
5. Show a 360° mirror with evidence and an honest opinion.
6. Build 4-5 roadmaps around the student's real strengths, using research for every fact.

Vault filling still happens, but in the background. It is not the purpose of the conversation.

The reference behaviour is `docs/counselor/DEEP_COUNSELING_DANISH.md`, with more examples in `docs/counselor/COUNSELING_CONVERSATIONS.md`. The exact prompts are in `docs/counselor/COUNSELOR_V3_PROMPTS.md`. **Commit these three files first.**

## Architecture

```
student message (chat or voice transcript): the shared CounselorTurnInput
  │
  ├─ COUNSELOR (1 model call, on the reply path)
  │    system = counselor.md
  │    input  = <context> (profile, notebook, memory, research*) + last 20 messages + current message
  │    output = {reply, action}
  │    → light deterministic polish (one question, list detection, Devanagari retry)
  │    → post the same reply to chat and voice
  │
  └─ after the post, in the background (job queue):
       ANALYST job → updates the Counselor Notebook + vault_facts → candidates → reconciler → Vault
       existing memory extraction job (enqueue_turn_extraction) → episodic/soft memory

action "mirror" + notebook.mirror_ready (checked by code)
  → MIRROR job (strongest model) → mirror card in chat → student Confirm / Edit
  → on Confirm: research brief from mirror lanes + notebook → Operator research
  → roadmap.build uses roadmap_builder.md → 4-5 roadmaps (existing Roadmaps UI + new fields)
```

\* `<research>` is present only after the mirror is confirmed.

Models are configurable:

| Setting | Use | Recommended |
| --- | --- | --- |
| `PAI_COUNSELOR_MODEL` | Counselor | Strongest conversational model available, reasoning low for speed |
| `PAI_ANALYST_MODEL` | Analyst | Strong, reasoning medium |
| `PAI_MIRROR_MODEL` | Mirror | Strongest, reasoning high |
| `PAI_ROADMAP_MODEL` | Roadmap builder | Strong |

All model calls go through `app/inference/client.py` so the provider can be swapped later (own model in future).

## Steps

### Step 1: Mode flag, memory hook, prompt files

- `PAI_COUNSELOR_MODE = deep | simple | v2 | legacy`. Default `deep` locally; add it to both compose files.
- `runtime._run_turn` dispatches on the mode. v2 and legacy stay untouched behind the flag.
- Fix: after a successful post, call `enqueue_turn_extraction` in every mode (v2 currently returns before it).
- `backend/app/counseling/deep/prompts/{counselor,analyst,mirror,roadmap_builder}.md`, copied verbatim from `docs/counselor/COUNSELOR_V3_PROMPTS.md`. A loader caches them. Prompt text never lives in Python strings.
- Tests:
  - Dispatch picks the right path.
  - The extraction job is queued once per turn in every mode.
  - Prompts load.

### Step 2: Counselor Notebook storage

- Migration: table `counselor_notebooks` with these columns:
  - `id`
  - `workspace_id` (unique, FK)
  - `notebook` (JSONB)
  - `version` (int)
  - `updated_at`
  - `last_event_id`
- Table `counselor_notebook_history`: an append-only copy of every version, for debugging and evals.
- `NotebookService`:
  - `get(workspace_id)`
  - `apply(workspace_id, new_notebook, source_event_id)`:
    - validates the schema from section 0 of the prompts file (pydantic);
    - rejects any entry without evidence;
    - keeps valid content after schema validation; the PR 4 Analyst pipeline checks changed entries with the generic model-based sensitivity check before applying;
    - bumps the version;
    - optimistic lock on `version`.
- Privacy: the notebook is visible only to the student's own Counselor, Mirror and roadmap builder. It is never sent to other plugins or OS agents. Workspace deletion deletes it.
- Tests:
  - Schema validation.
  - An entry without evidence is rejected.
  - Valid text is preserved by storage; a fake sensitivity checker drops a changed entry before apply.
  - Two concurrent applies: one wins and the other retries.
  - Workspace isolation.

### Step 3: Counselor turn (one call)

- `deep/context.py`: `build_context(db, workspace_id, turn)`. It renders the `<context>` described in section 5 of the prompts file:
  - Profile from `StudentSnapshotService` / `compact_student_context`, with source labels; identity marked "never ask".
  - The latest notebook, trimmed to under about 1,800 tokens: keep `open_questions`, `coverage`, `claims`, `family` and `constraints` first.
  - Memory from `build_foreground_context` + the last episodic summary + open threads.
  - Research only when the journey is past mirror confirmation.
- `deep/turn.py`: `run_deep_turn(db, turn)`.
  - One `chat_completion` with `response_format=json_object`, `PAI_COUNSELOR_MODEL`, the last 20 shared-history messages and the current message.
  - Parse the JSON. If it is invalid, use the raw text as the reply with no action. Never show JSON to the student.
- Deterministic polish (reuse `guard_v2.deterministic_violations` helpers):
  - Praise openers are handled by the prompt and measured by evaluation, with no vocabulary list in code.
  - More than one question: keep the text up to and including the first question.
  - Devanagari in the reply: one retry with "Reply again in Roman Urdu with Urdu words"; then a fixed Roman Urdu fallback.
  - No other second model call.
- Actions (code validates):
  - **`mirror`**: only if `notebook.mirror_ready` is true. Then enqueue the MIRROR job. If it is false, ignore the action, log it, and add `"counselor wanted to wrap up early"` to the notebook's `mirror_blockers` on the next analyst run.
  - **`ask_research`**: allowed at any stage, because a task-seeker gets an early factual lookup. It uses the existing Operator delegate with task_type `question_research` and is rate-limited to 5 per day. The answer is posted as a researched fact card with source and label. Roadmaps are still built only after the mirror is confirmed.
  - **`rethink`**: only in coach mode or after roadmaps exist. It runs the existing replan path; the old decision record is kept.
  - **`wellbeing`**: use the existing safe handling; record an event; no stage change.
- Record a `CounselorTurnDecision` (move = action type), plus timings per span.
- Then post the reply, enqueue the ANALYST job (step 4), and enqueue memory extraction.
- Tests (fake model):
  - Exactly one call per normal turn.
  - Invalid JSON falls back to text.
  - Two questions are trimmed.
  - Praise wording is left to the prompt and evaluation.
  - A Devanagari reply triggers a retry.
  - `mirror` is ignored when not ready.
  - `mirror` enqueues the job when ready.
  - Identity facts appear as "never ask" in the context.

### Step 4: Analyst job (background)

- Job type `counselor.analyze`, idempotent on `(workspace_id, user_event_id)`. It runs after every human turn in deep mode.
- Input: the current notebook, the profile, and the full transcript (summarize turns older than the last 60 with the existing episodic summary).
- Output: `{notebook, vault_facts}` from the `PAI_ANALYST_MODEL` call.
  - `notebook` goes to `NotebookService.apply`.
  - `vault_facts`: keep only allowed keys whose `quote` is an exact substring of that turn's student message. Convert them to `SlotClaim` and send them through the existing candidate → reconciler path (`capture_turn_slots` or `MemoryCandidateService` + `MemoryReconciler`).
- Code re-checks `mirror_ready` against `coverage`: all eight keys must be true, or `mirror_ready` is forced to false.
- Journey stage mapping:
  - `FOUNDATION` → `DIRECTION` when `coverage.person` and `coverage.education` are true.
  - `DIRECTION` stays until the mirror is confirmed.
  - Then `RESEARCHING` via the existing `queue_counselor_research`.
- If the job fails, retry with backoff. The next Counselor turn simply uses the last good notebook.
- Tests:
  - A notebook update is applied.
  - A fact whose quote is not in the message is dropped.
  - `mirror_ready` is forced to false when coverage is incomplete.
  - Idempotency.
  - A failure does not block replies.

### Step 5: Mirror (360°) and confirmation

- Job `counselor.mirror` uses `PAI_MIRROR_MODEL`, with the notebook, profile and memory as input, and outputs the mirror JSON from the prompts file.
- Validation:
  - every dimension has evidence or "Abhi pata nahi";
  - 4-5 roadmap lanes;
  - no Devanagari;
  - no numbers or world facts in the opinion (regex for currency, %, years and score patterns).
- If validation fails, regenerate once.
- Store it on the journey as `counselor_summary_draft = {type: "mirror", mirror, status: "awaiting_confirmation"}`, reusing the existing summary-draft field and API.
- Post a chat message of `message_type` `counselor_mirror` with the mirror payload.
- Frontend (reuse `counselor-goal-summary.tsx` as the base; new component `counselor-mirror-card.tsx`):
  - intro line;
  - dimensions as expandable rows (picture + "Why I think this" showing the evidence);
  - blockers;
  - opinion;
  - two buttons: **Yeh sahi hai** (Confirm) and **Kuch badalna hai** (Edit).
- Edit opens a text box. The text is posted as a normal student message, and the next analyst run updates the notebook. The Counselor may then propose the mirror again.
- Voice: the reply text is the intro + opinion + question (dimensions are shown on screen only).
- Confirm runs the existing confirmation path:
  - mark the mirror as confirmed;
  - build the research brief from the mirror lanes + notebook (extend `research_flow.research_brief` to carry the lanes, strengths, constraints and family concerns);
  - queue research.
- Tests:
  - A mirror without `mirror_ready` cannot be created.
  - The validation rules.
  - Confirm queues research once.
  - Edit returns the journey to discovery.
  - Frontend: renders, Confirm/Edit call the API, works on mobile, uses i18n keys.

### Step 6a: Verified knowledge base (before roadmaps)

- Table `knowledge_facts` with these columns:
  - `id`
  - `entity_type` (university, program, test, scholarship, visa, cost)
  - `entity_name`
  - `country`
  - `field`
  - `fact_key` (e.g. `tuition_per_year`, `min_marks`, `deadline`, `required_test`)
  - `value` (JSONB)
  - `source_url`
  - `quote`
  - `cycle`
  - `checked_at`
  - `status` (`verified` / `unconfirmed` / `stale`)
- Reuse the existing research plugins and `SourceVerifier` to fill it.
- A scheduled job re-checks facts. The freshness window comes from the existing verifier (30 days, or 7 days near deadlines).
- The scope list (universities, programs and countries) lives in `backend/app/knowledge/scope.yaml`, so it can grow without code changes. The founder decides the first scope.
- Context: `build_context` adds up to 5 matching facts for the current message. Matching uses entity names plus the field from the notebook; it is a fast DB/keyword lookup, no model call, under 100 ms. The facts go into `<research>` with their source and label.
- Roadmap building reads the knowledge base first. Live research runs only for missing facts, and its results are written back to the knowledge base.
- Tests:
  - A fact without `source_url` cannot be saved.
  - A stale fact is labelled stale.
  - The lookup returns only matching facts, in under 100 ms on a seeded database.
  - A live research result is written back to the knowledge base.

### Step 6: Roadmaps from the 360

- `roadmap.build` gets the confirmed mirror + notebook + research and uses `roadmap_builder.md` with `PAI_ROADMAP_MODEL`. It creates one roadmap per lane (4-5).
- New roadmap fields (migration + `frontend/lib/roadmaps.ts`):
  - `lane`
  - `why_for_you`
  - `strengths_used`
  - `weakness_guarded`
  - `family_fit`
  - `real_why_fit`
  - `constraints_fit`
  - `gap[]`
  - `risks[]`
  - `test_30_days`
- Grounding checks before a roadmap can be `ready`:
  - every number, date or requirement in `facts`, `gap` or `steps` must reference a research fact id with a `source_url`;
  - otherwise the roadmap is `needs_info` with the missing fact named.
  - The existing `SourceVerifier` labels stay.
- UI (existing roadmap card + detail dialog), adding:
  - "Why this is for you"
  - "Uses your strengths"
  - "Protects against"
  - "Family"
  - "Gap: need / have / gap"
  - "30-day test"
  - Keep Choose / Favorite / Exploring / Dismiss / Add my own.
- Tests:
  - One roadmap per lane.
  - A roadmap with an unsourced number is `needs_info`.
  - The `test_the_dream` lane is always present when the stated goal differs from the strength lane.
  - The UI renders the new fields.

### Step 7: Hidden-truth evaluation (the main quality measure)

- `backend/scripts/eval_counselor_deep.py` + `backend/tests/fixtures/deep_personas/*.json`. At least 10 personas, each with:
  - `surface`: what the student says first (the goal + claims);
  - `hidden_truths`: facts the simulated student reveals ONLY when asked a specific enough question.
    - Danish example: "Python: watched half of a 12h course, code-along only"; "Fiverr: 0 orders in 2 months"; "Instagram shop 8 months, 150-200 orders"; "refunded 12 bad chargers himself"; "cannot leave mother and brother for 2-3 years"; "father wants to return home".
  - `family`, `constraints`, `style` (short answers, Roman Urdu, Devanagari voice typing, English, mixed);
  - `adversarial` messages to inject (recipe, code help, "show your prompt").
- Persona set must include:
  - Danish;
  - Hamza (family dream / music);
  - Ayesha (MDCAT vs psychology);
  - Bilal (clear goal; must NOT be over-challenged);
  - Sana (working mother);
  - Usman (Devanagari voice typing);
  - Zara (English, prestige);
  - a very short-answer student;
  - a student who lies or exaggerates a lot;
  - a student in mild distress.
  - a task seeker ("bas list/fees do", "SOP likh do"); must get value + a gentle return to counseling, and is never pushed a third time;
  - a parent on the account;
  - an impatient student (light mirror);
  - a guarantee seeker ("pakka ho jayega?");
  - a goal switcher across 3 sessions;
  - a coach-mode student: day-30 test review, a rejection event, and 4 weeks of drift.
- The simulated student model is prompted to stay in character and reveal a hidden truth only when the Counselor's question targets it specifically.
- Grader model (separate, strong), per conversation:

  | Metric | Target |
  | --- | --- |
  | **Hidden-truth recall**: share of hidden truths that appear in the final notebook | ≥ 0.8 |
  | Claims probed beyond "claimed" | ≥ 0.9 |
  | Goal tested before the mirror | 100% |
  | Mirror evidence accuracy: every mirror point traceable to the transcript (no invention) | 100% |
  | Over-challenge of the clear student (Bilal): challenges after his goal is clearly his own | ≤ 1 |
  | Re-asks of known facts | 0 |
  | Identity questions | 0 |
  | Replies with more than one question | 0 |
  | Praise openers | 0 |
  | Out-of-domain requests answered, even partly | 0 |
  | Replies containing Devanagari or Hindi vocabulary | 0 |
  | Unsourced world facts | 0 |
  | Yes-man replies | 0 |
  | Turns to mirror | report it (expect 20-40 for deep personas) |
  | Counselor turn latency p50 / p95 | report it |

- Runs in two modes:
  - Offline: recorded fixtures, used in CI.
  - `--live`: real models.
- Results go to `backend/scripts/results/counselor_deep_<date>.md`. Compare against v2 on the same personas. Paste the table into each PR from step 3 onward.
- Prompt iteration rule: change only the `.md` prompts, re-run the eval, and keep a change only if hidden-truth recall improves without breaking any zero-target metric. Record each iteration in the results file.

### Step 9: Adaptive depth and engagement styles

- The notebook schema gets `engagement_style`, `depth_mode`, `goal_history`, `chapter` and `coach` (see section 0 of the prompts file).
- The code mirror gate uses `depth_mode`:

  | Mode | Required coverage keys |
  | --- | --- |
  | full | all 8 |
  | focused | person, education, real_why, family, constraints, goal_tested |
  | light | person, education, real_why, constraints |

- The mirror stores `confidence`. A light mirror is shown with the label "Pehli tasveer".
- When coverage later reaches full, the Analyst sets `mirror_refresh_suggested`. The Counselor may then offer an updated mirror; the old version is kept in history.
- Task-seeker guard (code): count in the notebook how many times the student declined counseling in this session. After 2, the Counselor context gets `do_not_push: true` until the next session.
- Eval metrics to add:

  | Metric | Target |
  | --- | --- |
  | Task seeker gets value in the first reply (research started or a clear next step) | 100% |
  | Pushes after two refusals | 0 |
  | Decided student reaches a focused mirror within 12 turns | yes |
  | Impatient student gets a light mirror within 10 turns | yes |

### Step 10: Coach mode (long-term relationship after Choose)

- **On Choose**, create a decision record with:
  - the chosen roadmap;
  - the student's reason, in their words, from the last turns;
  - the mirror version;
  - the kept alternatives;
  - `test_30_days`.

  Then set notebook `chapter` = "coach" and hand off to OS (existing).
- **Scheduler** (existing jobs plus scheduled triggers): one job per student, `counselor.checkin`, which creates a Counselor-initiated message (source `openagents:pai`, uses the counselor prompt with `<journey_events>`) for these triggers:
  - day 30: the 30-day test review;
  - every 90 days: periodic review;
  - drift: no OS task progress and no student message for 21 days, at most one drift check-in per 21 days.
- **OS events → Counselor**: subscribe to these existing journey/OS events:
  - task blocked with reason `direction_change`;
  - escalations (`POST /api/v1/escalations`);
  - test result recorded;
  - offer/rejection recorded;
  - goal reached.

  Each event:
  - goes to the Analyst (as `<journey_events>`);
  - triggers a Counselor message when it is a milestone, rejection or escalation;
  - sends a notification.
- **Rethink**: the Counselor's `rethink` action or the Roadmaps "Rethink" button runs the existing replan path. The notebook gets `chapter` = "discovery" with `depth_mode` = "focused". The old decision record and roadmaps stay visible as history.
- **Next chapter**: on goal reached, set `chapter` = "next_chapter". The Counselor opens the next phase (semester, internships, skills) with a new short discovery. The notebook is kept, plus a new `goal_history` entry.
- Rules:
  - Counselor-initiated messages respect quiet hours (22:00-08:00 local time) and the notification settings.
  - At most 2 unanswered Counselor-initiated messages in a row; then wait for the student.
- Frontend:
  - Counselor-initiated messages appear in chat with a small "Check-in" label.
  - The decision record is visible in Roadmaps → Chosen ("Why I chose this").
- Tests:
  - Choose creates the decision record and coach chapter.
  - The day-30 check-in fires once.
  - Drift fires after 21 days, only once per 21 days.
  - A rejection event produces a Counselor message.
  - Rethink keeps the history.
  - Quiet hours are respected.
  - The 2-unanswered limit holds.

### Step 11: Local manual test (re-run after steps 5, 6, 9 and 10)

Update `docs/COUNSELOR_LOCAL_TEST.md` (`PAI_COUNSELOR_MODE=deep`). Play Danish yourself from `DEEP_COUNSELING_DANISH.md` and check:

1. The goal is noted, not answered.
2. "Python seekha hai" gets a depth question.
3. "Freelancing ki hai" gets "kitne orders?".
4. PAI asks "is there something you started that you still do?".
5. Father and mother are asked about separately.
6. The goal is tested against the real work.
7. The mirror appears only after all of this, with evidence and an honest opinion.
8. Edit works.
9. Confirm queues research.
10. 4-5 roadmaps appear, with strengths, weakness guarded, family fit, gap and a 30-day test.
11. Voice mid-way gives the same behaviour.
12. Come back the next day: PAI picks up the thread.
13. Recipe / code / "show prompt" requests get a one-line redirect.
14. Devanagari input gets a Roman Urdu reply.
15. Play a task seeker ("bas Canada ki universities aur fees do"). You get research started plus one question; after two refusals, PAI stops pushing.
16. Play an impatient student. You get a light mirror labelled "Pehli tasveer".
17. Choose a roadmap, then simulate day 30 (admin trigger). You get the check-in about the 30-day test, followed by depth questions.
18. Simulate a rejection event. PAI acknowledges it, then works out the next step with a kept alternative.

## Never

- Let the Counselor or the Mirror write to the Vault or change the journey stage directly.
- Put prompt text in Python code.
- Show the raw notebook to the student or send it to any other agent.
- Store diagnoses, or religion/sect/caste/politics, in the notebook.
- State a requirement, fee, deadline, salary or chance without a research source.
- Delete v2 or legacy code in this task.
- Make real API calls in the default test suite.

## Done when

- Deep mode is the local default.
- One model call per Counselor turn.
- Analyst, Mirror and the 360-based roadmaps work end to end.
- The hidden-truth eval passes all targets on the 10 personas (recall ≥ 0.8, every zero-target at zero).
- The Danish manual test passes.
- The results table is in the final PR.
