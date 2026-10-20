# PAI C Counseling Policy v2 — one universal policy (17 Oct 2026)

Decision: no separate code path per student type. One universal counseling loop for everyone, carried by a strong model (moving to Opus-class), with a small set of hard guardrails in code that must never fail. Student types (confused, decided, task seeker, parent, returning, impatient, adult switcher...) are examples the model handles inside the same loop, not branches.

## The universal loop (every reply)
1. What do they need right now? Care / help with a request / to be heard / direction / to be understood. Respond to that first.
2. What can I give them? Reflection that adds meaning, a pattern, a summary, an honest first impression, general information (world facts only from research).
3. What do I still need to know to help them well? Use the coverage map. Ask one simple question only if a gap matters now; often no question is best.

## Hard guardrails (code, always enforced)
1. Safety: classifier -> care path.
2. Requests are stored and never blocked.
3. Questions: at most one meaningful question per reply, never a required ending. The classifier supplies `question_needed` (default false); both tables use it instead of a fixed question ratio. Requests may ask for necessary context, and a picture may invite correction. Several helpful statements may follow each other. Missing areas alone do not justify questions.
4. No repeated question or repeated reply.
5. Mirror only when allowed (stage, no pending job, corrections absorbed); a correction is explored first.
6. A first picture is provisional and shared once: at least 4 evidence-covered areas including status and history support it; there is no minimum message count. Coverage is a supporting indicator, not proof of understanding. Mirror readiness is recomputed from active evidence and depth-specific coverage; corrections require an applied Planner patch, not two extra turns. Student review remains required for confirmation.
7. Coverage depth tracked in code (min items per area) and shown to the model as known/missing.
8. Every turn logged (model moves + guardrail flags) for evaluation.

## Modes
PAI_POLICY_MODE = guided (universal loop + guardrails, default for strong models) | strict (full decision table, kept as fallback). Choose by measured results on the same persona set and live tests.

## Success measures
Measure felt understood, appropriate questions, corrections respected, source accuracy, and informed student choice. Do not optimize a reflection/question ratio or a fixed picture deadline. Offline tests demonstrate routing and guards; counseling quality needs reviewed student conversations.

## Adaptive whole-person counseling (19 Oct 2026)

The ten canonical areas stay stable. `understanding/capability_mapping.json` maps them to daily life, experiences, accomplishments, relationships, values and changing aspirations. These are in-domain even without an immediate application task. Self-description and reported projects remain `said`; new independently evidenced items or demonstrated capabilities require a shown/confirmed profile reference. Interpretations remain correctable and private; a family preference does not establish pressure or a controlling relationship.

Paths-first is the default decision strategy, not an information gate. A direct information request can use `research.gateway` -> the existing bounded `research.claim` job -> SourceVerifier -> Messenger at any stage. Current source receipts enter the same Counselor context. Missing sources leave the request unanswered with an honest response. Care defers delivery. Information never chooses a roadmap or authorizes OS execution. Personal recommendations still need relevant student evidence, current world evidence and uncertainty; selection keeps the existing confirmation and authorization gates.

See [ADAPTIVE_COUNSELING_REPORT.md](archive/ADAPTIVE_COUNSELING_REPORT.md) for implementation evidence, scenario coverage and limitations.

See also PAI_C_WORKFLOW_LOCK_V1.md (locked engineering workflow, 18 Oct 2026) and the Figma board https://www.figma.com/board/NjVJfdxERWfRHPycy1wDkF
