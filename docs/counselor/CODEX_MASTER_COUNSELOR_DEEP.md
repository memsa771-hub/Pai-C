# Codex master task: rebuild PAI Counselor as a deep counselor (dev → roadmaps)

This is the **only** Codex prompt to follow. It replaces every earlier Counselor prompt: v1, core, complete, simple, and `RUNTIME_PROMPTS.md`. If this file and any other document disagree, this file wins.

## 0. Repo, branch, rules

- Repo: `memsa771-hub/Pai-C`. Start from `dev` at commit `9f5f4c5` ("Restore PAI OS alongside Counselor on dev") or later.
- Create branch **`feature/counselor-deep`** from `dev`. Open one PR per milestone into `feature/counselor-deep`; when everything is done, open one final PR into `dev`. Never push to `main`.
- **Scope: the Counselor up to roadmaps only.** Do not change anything in PAI OS (applications, tasks, deadlines, files, application workspace, OS navigation), even though it is on `dev`. The existing Choose button and decision flow stay exactly as they are.
- The default test suite must run offline (fake models, recorded fixtures). Every PR keeps `pytest` and the frontend tests green.
- Prompt text lives only in `.md` files, never in Python strings.

## 1. Sources of truth (read before coding)

### 1.1 Figma workflows (use the Figma MCP `get_figjam`)

| Board | Link | Use |
|---|---|---|
| **PAI Counselor to Roadmaps** (primary) | https://www.figma.com/board/4wp4bSG5cmlQlhd2BbdIKL | 01 End to end (no OS) · 02 One turn, fast path · 03 Domain and grounding check · 04 Knowledge base and roadmap build |
| **PAI Counselor workflows** (secondary) | https://www.figma.com/board/tsOnWhN6MVs6aoNzWoAVYV | 01 Any user, any message · 02 Deep counseling loop · 03 No hallucination layers. **Ignore 04 (coach mode): deferred** |

Older boards are superseded: `oa2J6dzDVj0w9G7vwuX21X` (Counselor Workflows) and `FySI0hHwWa1wXG0l69SN9I` (Full System). Do not follow them where they conflict with the boards above.

### 1.2 Documents (commit them into `docs/counselor/` in PR 1, exactly as supplied)

| File | What it is |
|---|---|
| `COUNSELOR_V3_PROMPTS.md` | The exact prompts: Counselor, Analyst, Mirror, Roadmap builder, Notebook schema, context template |
| `CODEX_COUNSELOR_V3_DEEP.md` | Detailed per-step specs (steps 1-7, 9, 6a, 11). **Branch and base in that file are overridden by section 0 here. Step 10 is deferred. Its step 4 "vault_facts" is removed (see 3.4)** |
| `DEEP_COUNSELING_DANISH.md` | Reference behaviour: one deep conversation, the 360 mirror, roadmaps |
| `COUNSELING_CONVERSATIONS.md` | Six more students (reference behaviour) |
| `COUNSELOR_REAL_WORLD_AND_LIFECYCLE.md` | Handling every kind of user (Parts 1-4 are in scope; Part 5, coach mode, is deferred) |

Keep `docs/counselor/EXAMPLES.md` as history (its failing transcript is still a regression case), but where it differs, the new conversation files win.

**Precedence when sources disagree:** this file > `COUNSELOR_V3_PROMPTS.md` > the primary Figma board > `CODEX_COUNSELOR_V3_DEEP.md` > reference conversations > older docs.

## 2. What exists on `dev` today (validated)

- `PAI_COUNSELOR_V2=true` (in `config.py`) routes turns to `counseling/turn.py`. That path makes 3-6 model calls per turn: scope + extraction (+ recovery), writer, guard model, and a rewrite. It is slow and scripted.
- `runtime._run_turn` returns early in v2 mode, so **`enqueue_turn_extraction` never runs for v2 turns**: background memory formation is skipped.
- `memory/handlers.py` calls `advance_discovery_stage` and `delegate_research_if_ready` after reconciliation. `stages.advance_discovery_stage` moves `DIRECTION → RESEARCHING` automatically as soon as the goal has a stated preference, an objective and constraints. That **starts research without the student confirming anything**. In deep mode, research must start only after the mirror is confirmed.
- Research, plugins, `SourceVerifier`, roadmaps, student requests, escalations, the decision flow and the Counselor frontend components (summary card, request panel, research status, roadmap card/detail/choice dialogs) all exist and are good. **Reuse them.**

## 3. Delete, keep, change

### 3.1 DELETE in this task (the v2 turn engine, used only by the v2 path and its tests)

Before deleting, move these few reused pieces into `app/counseling/deep/`:

- `CounselorTurnInput`, `shared_history` and `_returning` from `turn.py` → `deep/turn_input.py`.
- Deterministic helpers from `guard_v2.py` (praise-opener list, question counting, list detection, a Devanagari check you add) → `deep/polish.py`.

Then delete:

| Delete | Why |
|---|---|
| `app/counseling/turn.py`, `scope.py`, `writer.py`, `move.py`, `summary.py`, `guard_v2.py` | The v2 multi-call engine |
| `app/counseling/extraction.py`, `slot_capture.py`, `slots.py` | Only used by the v2 engine. The Vault is filled by the existing memory extractor (see 3.4). Delete only after confirming with `grep` that nothing else imports them |
| Tests: `test_counselor_v2_channel_parity.py`, `test_counselor_v2_guard.py`, `test_counselor_v2_move.py`, `test_counselor_v2_summary.py`, `test_counselor_v2_journey_pg.py`, `test_counselor_slots.py`, `test_counselor_extraction.py` | Their code is gone. Port any still-relevant assertion (re-asks, praise openers, channel parity) to the new deep tests |
| `scripts/eval_counselor_sim.py` | Replaced by `scripts/eval_counselor_deep.py`. Keep any useful code from `counselor_eval_support.py` in the new script |
| `docs/counselor/RUNTIME_PROMPTS.md` | Simple-mode prompts, replaced by `COUNSELOR_V3_PROMPTS.md` |
| Consolidation | Deep is the sole Counselor path; successful human posts queue extraction and analysis. |

**Database:** do NOT drop tables or rows created by migrations 082/085/087/089 in this task, even if they become unused. List them in the final PR as follow-up cleanup.

### 3.2 Consolidation status

The temporary legacy runtime has been removed in PR 5b-2. Shared understanding,
projection, baseline, discovery, policy and state remain. See
[CLEANUP_AFTER_DEEP.md](CLEANUP_AFTER_DEEP.md) for exact importers and the backup tag.

### 3.3 KEEP and REUSE (do not rewrite)

- `memory/*`: Vault, candidates, reconciler, extractor, episodic, foreground, `turn_hook`.
- `counseling/research_flow.py`, `stages.py`, `student_requests.py`.
- `plugins/*` (research, verification, `roadmap_builder`), `research/`, `roadmaps/`, `journey/`.
- `routers/roadmaps.py`, `routers/student_requests.py`, `routers/escalations.py`.
- Frontend:
  - `components/roadmaps/*`
  - `components/chat/counselor-request-panel.tsx`
  - `counselor-research-status.tsx`
  - `counselor-voice-control.tsx`
  - `roadmap-comparison.tsx`
  - all OS components untouched.

### 3.4 CHANGE

| File | Change |
|---|---|
| Consolidation | Deep is the sole Counselor path; successful human posts queue extraction and analysis. |
| `counseling/stages.py` | `advance_discovery_stage(..., allow_auto_research: bool)`. In deep mode it is `False`: `DIRECTION → RESEARCHING` happens only through mirror confirmation |
| `memory/handlers.py` | In deep mode, do not call `delegate_research_if_ready` from reconciliation unless the journey is already past mirror confirmation (stale-refresh in `PROPOSED`/`CHOSEN` keeps working) |
| Analyst (`COUNSELOR_V3_PROMPTS.md` §2) | Produces only the notebook. **No `vault_facts`**: the existing `memory.extract` job (via `enqueue_turn_extraction`) fills the Vault through candidates → reconciler, as it already does |
| `routers/roadmaps.py` "discuss roadmap" message | In deep mode, generate it through the deep Counselor turn (`counselor.md` with `<research>` containing that roadmap) instead of the legacy `CounselorModelProvider` |
| `frontend/components/chat/counselor-goal-summary.tsx` | Replaced by `counselor-mirror-card.tsx` (PR 6). Delete the old component once the mirror card is live and nothing imports it |

## 4. Build: milestones, one PR each

Detailed specs for each milestone are in `docs/counselor/CODEX_COUNSELOR_V3_DEEP.md` (step numbers in brackets).

| PR | Milestone | Spec | Done when |
|---|---|---|---|
| Consolidation | Deep is the sole Counselor path; successful human posts queue extraction and analysis. |
| **2** | Counselor Notebook storage + service | [2] (with the step 9 fields: `engagement_style`, `depth_mode`, `goal_history`, `chapter`; `coach` stays empty) | Schema validation, evidence required, workspace isolation; content checking follows the Analyst in PR 4 |
| **3** | Deep Counselor turn (1 model call) + polish + actions | [3] | One call per turn; JSON fallback; one-question trim; Devanagari retry; `mirror` and `ask_research` actions validated |
| **4** | Analyst job + stage gating (§3.4 stages/handlers) | [4] | Notebook updated after each turn; `mirror_ready` enforced by code per `depth_mode`; no automatic research before mirror confirmation |
| **5** | Hidden-truth eval harness (first 8 personas incl. Danish, Hamza, Bilal, the task seeker, short answers, Usman/Devanagari) | [7] | Offline fixture run in CI; `--live` report generated; targets reported (they don't have to be met yet) |
| **6** | Mirror (360) + mirror card + confirm/edit | [5], [9] (`mirror_confidence`, light label) | Mirror only when ready; every point has evidence; Confirm queues research once; Edit returns to discovery |
| **7** | Verified knowledge base + fast lookup in context | [6a] | `knowledge_facts` table; `scope.yaml` **empty by default: never seed invented facts**; lookup under 100 ms with no model call; live-research results written back |
| **8** | Roadmaps from the 360 (4-5 lanes) + new roadmap fields in the UI | [6] | One roadmap per lane; an unsourced number makes it `needs_info`; UI shows why-for-you, strengths, weakness guarded, family fit, gap, 30-day test |
| **9** | Eval targets + manual test + cleanup doc | [7] targets, [11] | All zero-targets at 0; hidden-truth recall ≥ 0.8 on Danish and ≥ 0.7 average; manual checklist passes; `CLEANUP_AFTER_DEEP.md` written |

**Prompt tuning rule (from PR 5 on):** change only the `.md` prompts, re-run the eval, and keep a change only if recall improves without breaking any zero-target. Log every iteration in `backend/scripts/results/`.

**Generic-only override for PR 3 onward:** no runtime vocabulary lists for sensitive content or praise. PR 4 checks each changed notebook entry with `deep/prompts/sensitive_check.md` in the background before `NotebookService.apply`; storage itself performs schema validation only. Daily research, notebook context, shared-history and reasoning settings have environment overrides. Praise is a prompt and evaluation concern.

## 5. Speed, grounding and domain (must hold in every PR)

- **Fast path:** context built with no model call; one Counselor call (streamed where the client supports it); deterministic polish. Target p50 under 3 s. The Analyst, memory extraction, research and mirror always run in the background.
- **Grounded:**
  - World facts come only from `<research>` (knowledge base or research results, with source and verified/unconfirmed label). Otherwise: "I will check".
  - Notebook entries need evidence.
  - The mirror is validated.
  - A roadmap number without a source makes the roadmap `needs_info`.
- **In domain:** prompt rules A/B/C/D. Out-of-domain requests and jailbreaks get one redirect line and never a partial answer. This is checked by the adversarial set in the eval.
- **Language:** mirror the student's language. Never Hindi or Devanagari; Devanagari input (voice typing) gets a Roman Urdu reply.

## 6. Never

- Touch PAI OS code, routes, navigation or data.
- Start research or roadmaps before the mirror is confirmed (except a single-fact `ask_research` lookup).
- Let the Counselor or Mirror write to the Vault or change journey stages directly.
- Seed the knowledge base with invented or unsourced facts.
- Show the raw notebook to the student, or send it to any other agent.
- Store diagnoses, or religion/sect/caste/politics, in the notebook.
- Put real API calls in the default test suite.

## 7. Final PR to `dev` must include

- The eval results table: deep vs. the old v2 numbers from `eval_reports/`, if present.
- Latency p50/p95.
- Screenshots of the mirror card and of the roadmap card/detail.
- `CLEANUP_AFTER_DEEP.md`.
- The list of unused DB tables and rows for follow-up.
