# Adaptive, person-first counseling — implementation and impact

Date: 19 October 2026. Branch: `pai-c`. Starting revision: `d3896258c5e07716e767b336008779ed609735fb`.
Specification: attached adaptive counseling task and [FigJam sections 00–12](https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF/PAI-C-Counselor-Workflow---01-Student-journey?node-id=0-1).

## A. Initial audit

| Area / board | Initial classification | Source evidence and disposition |
| --- | --- | --- |
| Ten-area understanding / 03 | Implemented but incomplete | `understanding/areas.json`, views and Truth Map v3 already support world/social/responsibilities/experiences. History projection missed project/achievement/activity/work records; broader capability mapping was not explicit in Planner context. Expanded without renaming areas. |
| Facts versus interpretation / 04 | Implemented but incomplete | Vault source levels, atomic Planner patches, private fields and sensitive pre-Mirror check existed. Planner could label a new self-report independently demonstrated without a supported reference. Added a provenance check; existing records are not rewritten. |
| Next move / 05 | Contradictory | Both JSON policy tables enforced question cadence; uncovered-area selection made a question the default. Added usefulness signal and removed the two-reply cap. Repetition and one-question guards remain. |
| Personal conversation / 03, 05 | Contradictory | Voice out-of-domain wording could reject personal life relevant to understanding. Voice and Planner now explicitly include ordinary life, relationships and experiences, without becoming therapy/general-purpose assistants. |
| First picture / 03, 06 | Contradictory | `first_picture_due` required eight messages even with rich evidence. Removed that count; retained supporting coverage/status/history and provisional review. |
| Mirror readiness / 06 | Implemented but incomplete | `apply_patch` passed the existing ready flag through an enforcement function that could clear it, but had no operation to set it for a new notebook. Recompute from active evidence and the selected depth. Light/focused reviews need not demand unknown pressure or certainty. |
| Correction / 06 | Implemented but partly mechanical | Retire/update/history/version conflict handling worked. Re-Mirror required both an applied patch and two more messages. Only the unnecessary count is removed. |
| Possibilities / 10 | Implemented but partly mechanical | Evidence-linked possibilities, statuses, review and authorization existed. Discovery required confirmation plus six messages; tentative reported experiences were effectively excluded by independent-kind checks. Offers now depend on evidence and mention receipts, not fixed spacing. |
| Direct information / 09, 10 | Missing before review | Requests were saved, but ordinary institution information could remain deferred until Mirror; Voice explicitly prohibited institution facts before H. Direct requests now use the existing bounded source-check job through the research gateway. |
| Source integrity / 09 | Implemented and tested, preserved | Exact quotations, SourceVerifier, cache freshness, grounding and eligibility services remain; unsourced direct results fail closed. No new eligibility estimates. |
| Memory / 02, 04 | Implemented and tested, preserved | MemoryService, Vault/reconciliation, session summaries, semantic Analyst reader, Truth Map storage/history and source labels remain. No alternate memory. |
| Jobs / 07, 12 | Implemented and tested, preserved | Existing Task Runtime, `research.claim` capability, budgets, idempotency, retry rules, Model Gateway and Messenger reused. No new queue, capability or framework. |
| Selection / 11 | Implemented and tested, preserved | Decision records, student requests, escalations and explicit selection/handoff contracts remain. Reading information or exploring does not authorize OS execution. |

“Implemented and tested” refers to available offline regressions, not a claim of production counseling quality. The board's white-card labels were not treated as evidence by themselves.

## B. Exact changes and reasons

Paths below are repository-relative.

| Files | Change / reason | Board |
| --- | --- | --- |
| `backend/app/pai_c/understanding/areas.json`; `backend/app/pai_c/understanding/capability_mapping.json` (new) | Map the existing ten areas to whole-person capabilities; project, accomplishment, contribution and work records support history. No incompatible taxonomy. | 03 |
| `backend/app/pai_c/deep/analysis.py` | Supply capability mapping; obtain eligible shown/confirmed profile references for atomic patch validation. | 02–04 |
| `backend/app/pai_c/planner/prompts/planner.md` | Multiple dimensions per message, reported versus independent experience, unknown family worry, corrections and changing aspirations; lighter provisional review instead of compulsory questions. | 03–06 |
| `backend/app/pai_c/planner/patch.py` | Reject new independent kinds, demonstrated capabilities or proven levels without a supported profile reference; recompute readiness from active evidence after an atomic patch. | 04, 06 |
| `backend/app/pai_c/planner/plan.py` | A reported experience in the existing `shown` collection can support a tentative possibility; still requires at least two visible evidence IDs. Its provenance is not upgraded. | 03, 10 |
| `backend/app/pai_c/deep/coverage_requirements.json` | Full retains all six internal coverage keys; focused requires said/shown/source/self; light requires said/self. These support provisional review, not certainty or permanent completeness. | 06 |
| `backend/app/pai_c/policy/classifier.py`; `backend/app/pai_c/policy/prompts/turn_classifier.md` | Add optional `question_needed`, default false. Sharing or an uncovered area alone is not sufficient reason to ask. | 05 |
| `backend/app/pai_c/policy/controller.py`; `backend/app/pai_c/policy/decision_table.json`; `backend/app/pai_c/policy/guided_table.json` | Both modes permit statement sequences and useful clarification without enforcing a two-question rhythm. Requests remain first after care; no introduction invitation blocks them. Guided decision help can precede confirmation. | 05, 06 |
| `backend/app/pai_c/policy/state.py` | Remove eight-turn first-picture threshold, two-turn correction wait, and six-turn discovery spacing. Keep evidence, applied correction, stage, pending-job and mention checks. | 03, 06, 10 |
| `backend/app/pai_c/policy/actions/discover.md`; `backend/app/pai_c/policy/actions/guide.md`; `backend/app/pai_c/policy/actions/summarize.md`; `backend/app/pai_c/policy/actions/adjust.md` | Tentative evidence-linked discovery and useful guidance/summary/pushback responses; instructions no longer require a closing question when the decision does not permit one. | 05, 10 |
| `backend/app/pai_c/voice/prompts/voice.md`; `backend/app/pai_c/voice/prompts/voice_guided.md` | Personal life in scope; no compulsory question; paths-first default; direct sourced information versus recommendation versus selection; family wish is not automatically pressure. | 03–06, 10 |
| `backend/app/pai_c/deep/prompts/mirror.md` | Read provenance rather than inferring independent proof from the collection name; avoid invented family worry and fixed personality labels. Existing generation/correction schema preserved. | 04, 06 |
| `backend/app/pai_c/runtime.py`; `backend/app/research/gateway.py` | After durable reply/decision, enqueue a saved direct information request through the existing gateway. Avoid a fast cache result overtaking acknowledgment; Voice wellbeing override prevents enqueue. | 02, 07, 09, 10, 12 |
| `backend/app/pai_c/myths.py`; `backend/app/pai_c/deep/prompts/myth_check.md`; `backend/app/pai_c/policy/myths.json` | Reuse bounded claim research for direct questions: exact-request cache, search/fetch, strict passage JSON, verbatim quote, SourceVerifier, date, delivery receipt. Care defers delivery; source absence stays unanswered. Copy/limits remain data. | 07, 09, 10, 12 |
| `backend/app/pai_c/deep/context.py` | Current verified information receipts are available before Mirror, in the existing research section. | 02, 09 |
| `backend/scripts/eval_policy_modes.py` | Accept the usefulness signal in offline replay; remove stale claim that guidance requires confirmation. No evaluation was run live. | 05 |
| `backend/tests/test_adaptive_counseling.py` (new) | Targeted fake-provider tests of stored state, real pipeline replies, research, provenance, safety and boundaries. | 02–07, 09–12 |
| `backend/tests/test_conversation_policy.py`; `backend/tests/test_policy_guided.py`; `backend/tests/test_question_cap.py` | Replace old cadence/count expectations with usefulness, meaningful review, preserved metadata and no-repeat behavior. Parameterized coverage retained. | 05, 06 |
| `backend/tests/test_possibilities.py`; `backend/tests/test_eval_policy_modes.py` | Evidence/mention-based discovery and first-picture coverage replace fixed spacing; conservative old fixtures without the new signal produce statements. | 03, 10 |
| `backend/tests/test_counselor_deep_pr3.py`; `backend/tests/test_counselor_deep_pr4.py`; `backend/tests/test_counselor_voice_v4.py` | Question-specific fixtures explicitly permit useful questions, so extraction/job ordering/repetition assertions test their intended path. Focused/light coverage expectations match current data. | 02, 05–07 |
| `backend/tests/test_voice_v5.py` | Immediate requests no longer contain a profiling invitation; persistence/dedupe/answered-event assertions retained. | 05 |
| `docs/counselor/COUNSELOR_V3_PROMPTS.md` | Runtime prompt sections synchronized verbatim. | 02–06, 09 |
| `docs/counselor/COUNSELING_POLICY.md`; `docs/counselor/PAI_C_WORKFLOW_LOCK_V1.md`; `docs/counselor/SPINE.md`; this report | Current policy, explicit amendment to historical lock wording, ownership/call-path notes, evidence and limitations. | 03, 05, 06, 10 |

No frontend styling, routes, navigation or schema migration was needed for these counseling corrections.

## C. Before / after student experience

The following are **offline examples with predetermined fake replies**, not transcripts from a live model:

1. **“Tell me about Example University.”** Previously saved for later research and vulnerable to profile-first diversion. Now the real runtime posts “I'll check current sources for that information,” saves and queues the request without a profile gate. A verified result later includes its source and checked date; missing evidence gets an honest unanswered response. Neither result is an eligibility verdict.
2. **“I help at the shop, study, and edit videos at night.”** Previously uncovered-area logic could follow with another question regardless of usefulness. The tested reply is “Your days combine responsibilities, learning and something you choose for yourself.” An appended unnecessary question is removed. Separate patch tests preserve multiple life dimensions without marking creative ability proven.
3. **“My parent prefers a stable career for me.”** The recorded person has a wish, but worry remains empty and supportive remains unknown. The fake visible reply says “That is their preference. It does not tell me yet how you feel about it.” It does not infer control.
4. **“I used to want research; now time with family matters more.”** A helpful statement can acknowledge the changed priority. Retiring an earlier interpretation removes it from active Voice context while retaining history. Existing roadmap choice is not silently rewritten.
5. **Rich information in two turns.** Evidence-covered status/history plus two other areas can enable a provisional picture. Two hundred empty turns cannot. Light review can leave family and certainty unknown, with later correction still available.

## D. Understanding impact and scenario evidence

| Requested scenario | Offline evidence | What remains empirical |
| --- | --- | --- |
| 1 Direct information with empty profile | Both modes queue one job only after acknowledgment; cross-workspace gateway input rejected | Retrieval coverage and usefulness of actual answers |
| 2 Multi-topic introduction | One patch records daily life, responsibilities, social, experience and self-perception; no mandatory questions | Model completeness/faithfulness on unscripted messages |
| 3 Personal conversation | Actual Voice path accepts friends/recreation and Roman Urdu fixture; visible reply has no forced question | Naturalness, tone and language matching |
| 4 Self-described strength | Untested `said` remains; unsupported demonstrated/proven update rejected | Avoiding subtle unsupported interpretations in free prose |
| 5 Completed project | Reported experience remains said; independent kinds require supported reference | Semantic match between a referenced record and capability claim |
| 6 Family influence | Preference saved without invented worry or control; visible reply remains neutral | Cultural sensitivity and appropriate follow-up timing |
| 7 No-question response | Both modes, repeated statement permission, actual guard removing appended question | Whether the model gives substantive value consistently |
| 8 Rich early context | First picture after evidence, not elapsed count; light readiness active-evidence tests | Whether the selected provisional depth feels sufficient |
| 9 Correction | Retire removes interpretation from current context, preserves history, invalidates unsupported readiness | Model recognition of nuanced corrections |
| 10 Unexpected possibility | Two visible evidence IDs including reported experience can yield tentative direction; existing discover mention receipt prevents repeats | Relevance and creativity of proposed directions |
| 11 Changing priorities | Visible statement example, correction/history tests; existing return-visit/session-summary regressions | Longitudinal consistency after weeks/months |
| 12 Execution boundary | Information creates no decision/run; existing possibilities, roadmap selection, OS contract tests retained | Real integration across separately deployed OS systems |

Whole-person coverage is broader without changing taxonomy. Evidence accuracy is better protected structurally, but schema validation is not semantic proof. Privacy, per-workspace scoping, source labels and private interpretation boundaries remain; no new sharing surface or global potential score was added.

## E. Verification

All verification is offline, with fake providers. `.env` was not edited; tests disable dotenv loading, unset `PAI_API_KEY`, and block external sockets. No paid model/API evaluation was run.

| Check | Result |
| --- | --- |
| Full backend, guided | 1,359 passed, 3 skipped, 8 subtests passed; 387.50 seconds |
| Full backend, strict | 1,359 passed, 3 skipped, 8 subtests passed; 394.62 seconds |
| New adaptive scenarios | 29 cases included in the full suite; 28 passed standalone before the final proven-level regression was added |
| Adaptive + Planner + Analyst targeted run | 108 passed, 37.09 seconds |
| Production-only security (the three skipped checks) | 3 passed, 4 subtests passed; 1.27 seconds |
| Frontend `npm test` | 60 passed in 18 files; 39.43 seconds |
| Frontend `npm run build` | Passed; Next.js compile, TypeScript and static page generation |
| Import every `app` module | 288 imported, 0 failures |
| `git diff --check` | Passed |

Backend warnings are the existing SQLite limitation reflecting an expression-based username index in migrations 101/107. No PostgreSQL migration was added or claimed tested. Full suites retain Mirror, roadmap, memory, stage, architecture and PAI OS contract regressions.

The backend wrapper used for commands is:

```python
import os, socket, sys, types, pathlib
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
os.environ.update(DATABASE_URL='sqlite://', APP_ENV='development', PYTHONDONTWRITEBYTECODE='1')
os.environ.pop('PAI_API_KEY', None)
tests = types.ModuleType('tests')
tests.__path__ = [str(pathlib.Path('tests').resolve())]
sys.modules['tests'] = tests
original = socket.socket.connect
def connect(self, address):
    if isinstance(address, tuple) and str(address[0]) not in {'127.0.0.1', 'localhost', '::1'}:
        raise RuntimeError('Offline test blocked external connection')
    return original(self, address)
socket.socket.connect = connect
os.environ['PAI_POLICY_MODE'] = 'guided'  # repeat with strict
from app.config import config
assert config.PAI_POLICY_MODE == os.environ['PAI_POLICY_MODE']
import pytest
sys.exit(pytest.main(['-q', '--tb=short']))
```

Executed via PowerShell here-string piped to `python -B -`, working directory `backend`. The final strict run additionally passed `-p no:cacheprovider`, avoiding shared pytest-cache writes while the independent guided process finished; test databases/providers were process-local. The `tests` namespace shim handles the local interpreter's installed package of the same name; it does not replace test code. Frontend commands: `npm test`, `npm run build` in `frontend`. Import verification uses `scripts.import_graph.graph` then `importlib.import_module` for every discovered application module under the same offline bootstrap. `git diff --check` is also run.

Initial runs exposed obsolete cadence/count assertions and two new-fixture errors (missing model import and a fake classifier marked as fallback). These were corrected without removing tests. A strict run then found the Mirror/roadmap shared Truth Map prompt equality contract; the new Mirror-specific paragraph was moved before the shared section, leaving that test unchanged. One mistakenly named targeted test path collected no tests; the actual `test_counselor_planner.py` suite is covered by the full runs. The historical baseline in BUILD_REPORT_V1 is 1,330 backend tests per mode; it is not presented as a fresh baseline run from this session.

## F. Compatibility and risks

- No migrations, tables, public endpoint signatures, new dependencies or queues. `question_needed` is an additive internal classifier field with false default; old recorded fixtures remain parseable. Old stored notebooks are not rewritten.
- Provenance checks apply to new patches, not a retrospective cleanup of historical overstatements. A valid reference proves provenance exists, not that an arbitrary interpretation is logically entailed; semantic review remains necessary.
- First-picture coverage remains a simple supporting heuristic (four areas, including status/history), not proof of deep understanding. The Mirror still requires generation validation, sensitive checking, version checks and student confirmation. It can still request a richer picture when evidence is inadequate.
- Source verification stays strict: an unrecognized official domain or no useful exact passage produces unanswered, not a guessed answer. Information research shares the existing bounded claim-check allowance. Capacity/provider failure leaves the saved request and queue retry behavior; it does not create an eligibility claim.
- The existing gateway can return `research_busy` before enqueue under concurrent PostgreSQL activity. The request remains saved/open, but this foreground call does not guarantee an automatic enqueue retry. Already-enqueued jobs use the existing worker retries. This is a remaining delivery-reliability limitation, not a source-verification bypass.
- The direct researcher currently returns a short attributed passage, not a comprehensive institution dossier or multi-part counseling answer. Existing selection/eligibility and roadmap generation remain separate.
- Facts delivered asynchronously are deduplicated by durable job/result/event receipts. A paused care state defers delivery using existing retry handling. Concurrent worker/database crash behavior was not exercised against live PostgreSQL in this task; no exactly-once delivery claim beyond tested queue/idempotency contracts is made.
- Grounding guards validate declared claims, cited values and numeric world assertions. They cannot guarantee the absence of every undeclared nonnumeric assertion or unsupported psychological implication. Prompt compliance and semantic interpretation require evaluation with real model replies after approval.
- Return-visit behavior uses existing session summaries; no new long-term counseling study or privacy/consent UX was introduced. No PAI OS execution code was rebuilt.

## G. FigJam consistency

Updated the existing board using the authorized saqlain connection. No cards, connectors or sections were added/deleted/moved. Bounds were returned by the edit tool; four section screenshots were inspected and three truncated labels shortened, then rechecked.

| Section | Mutated node IDs | Wording intent |
| --- | --- | --- |
| 03 | `37:386`, `37:408`, `37:448`, `37:456` | Stable taxonomy, broader history, provisional evidence-based picture without turn minimum, helpfulness while unknowns remain |
| 05 | `37:618`, `37:622`, `37:634`, `37:654` | Usefulness instead of question ratio; statement value; relevant respectful clarification; optional story question |
| 06 | `38:573` | Stages protect review/choice; revisit topics; not a help-access gate |
| 10 | `39:939`, `39:949` | Paths-first default; direct information at any stage; evidence for recommendation and consent for selection |
| Overview cross-references | `35:199`, `35:482`, `35:310`, `38:931` | Remove contradictory absolute institution/turn gates from the summary cards; reference the same default strategy and evidence requirements |

Four overview cross-references were also synchronized with those detailed sections, without layout changes, so their old absolute restrictions do not contradict the amended workflow. The repository lock document explicitly records the amendment while retaining its original historical text.

## H. Verdict and next validation

The existing Counselor now has adaptive question permission, broader whole-person framing, stricter provenance for new capability claims, evidence-based provisional review and a sourced direct-information route before Mirror. Selection and OS authorization remain separate.

The tests demonstrate state transitions, guards, preservation, source failure handling and visible fake-response behavior. They do **not** demonstrate live counseling quality. Next priority: an explicitly approved, budget-capped evaluation of actual replies across the twelve scenarios, followed by expert/student review for unnecessary questions, unsupported conclusions, useful direct answers and correction handling. No live calls were made for this task.
