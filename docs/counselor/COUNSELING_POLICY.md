# PAI C Counseling Policy v2 — one universal policy (17 Oct 2026)

Decision: no separate code path per student type. One universal counseling loop for everyone, carried by a strong model (moving to Opus-class), with a small set of hard guardrails in code that must never fail. Student types (confused, decided, task seeker, parent, returning, impatient, adult switcher...) are examples the model handles inside the same loop, not branches.

## The universal loop (every reply)
1. What do they need right now? Care / help with a request / to be heard / direction / to be understood. Respond to that first.
2. What can I give them? Reflection that adds meaning, a pattern, a summary, an honest first impression, general information (world facts only from research).
3. What do I still need to know to help them well? Use the coverage map. Ask one simple question only if a gap matters now; often no question is best.

## Hard guardrails (code, always enforced)
1. Safety: classifier -> care path.
2. Requests are stored and never blocked.
3. Questions: at most one per reply; no question after two asking replies in a row.
4. No repeated question or repeated reply.
5. Mirror only when allowed (stage, no pending job, corrections absorbed); a correction is explored first.
6. First picture due (once, around student message 8 with at least 4 areas covered, status and history covered): state tells the model; reply must share understanding + 3-4 directions in general words (fields, kinds of work, never institutions) with evidence.
7. Coverage depth tracked in code (min items per area) and shown to the model as known/missing.
8. Every turn logged (model moves + guardrail flags) for evaluation.

## Modes
PAI_POLICY_MODE = guided (universal loop + guardrails, default for strong models) | strict (full decision table, kept as fallback). Choose by measured results on the same persona set and live tests.

## Success measures
Reflections >= questions; felt understood >= 4/5; certainty before -> after; first picture by message 12; no repeated question; Gate 1: 7 of 10 real students reach the Mirror.

See also PAI_C_WORKFLOW_LOCK_V1.md (locked engineering workflow, 18 Oct 2026) and the Figma board https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF
