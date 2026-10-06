# Placement AI product blueprint

Design: [Placement AI — Student Journey & Product Blueprint](https://www.figma.com/design/dMXWWCNA4URa7crfdi2yNI)

Workflow board: [Placement AI — End-to-end student workflow](https://www.figma.com/board/0pbEdgDSgONU54tBcO4jTK)

The designs use fictional student **Amina Khan** and fictional institutions **Northbridge University** and **Riverfield College**. Every date, program, document and result in the mockups is illustrative.

## Product promise

PAI Counselor helps a student understand themselves and make better decisions. PAI OS gives the student one place to carry out the work. The student can work directly, ask PAI to coordinate, or switch between the two without losing their context.

One student identity and one canonical Vault sit underneath text, voice, Profile and application work. Voice is an interface to the same Counselor. New student claims pass through candidate, evidence and reconciliation before they become accepted profile context. An application plan records intended work and self-reported progress; it does not itself verify admission facts.

## Design file contents

| Page | Purpose |
| --- | --- |
| 00 · North Star | Two product modes, shared understanding, trust and delivery boundaries |
| 01 · Student Journey | Four stages, student-led and PAI-assisted paths, learning loop |
| 02 · PAI Counselor | Onboarding, counseling conversation, shared-context voice session |
| 03 · PAI OS | Profile, institution exploration, applications, requirements, deadlines, notifications, documents |
| 04 · Agentic Workflows | Research proposal, scoped execution, source-backed result, future approval gate, receipt and recovery |
| 05 · Foundations | Semantic palette, typography and reusable controls |
| 06 · Mobile & States | Mobile Counselor, applications, plan details, notifications, voice and error states |

The FigJam board adds a student workflow diagram and a counseling, memory and task-handoff sequence.

## Core workflows

1. **Start and understand:** student enters basics, then talks with PAI in text or voice. Counselor requests a bounded Student Understanding view. New claims become candidates and are reconciled before appearing in Profile or later context.
2. **Explore and decide:** student and Counselor identify several directions without turning interests into a fit verdict. Student can save institutions and compare sourced research. Gaps remain visible.
3. **Build application work:** student creates an institution and program plan, adds requirements from official sources, links documents and tasks, and tracks deadlines. All views reference the same plan.
4. **Ask PAI to help:** Counselor scopes a task. Operator executes through the relevant capability and returns evidence, limitations and artifacts to Counselor. Counselor explains the result to the student.
5. **Review and act:** the student reviews PAI's work, corrects profile information or plan details, and decides the next step. Sensitive external action requires a separate explicit approval and verified receipt.
6. **Continue:** deadline notices and scheduled reviews bring the student back to the same Counselor and PAI OS context.

## Delivery boundary

**Current implementation:** shared text/voice Counselor, Profile/Vault reconciliation, student-owned application plans, private institution entries, requirements, linked tasks/workflows, recurring reviews, documents, central deadlines and in-app notifications. The exact design layouts are a direction for the UI, not a claim that every screen already matches production.

**Future integration:** licensed global institution catalog, continuously verified official requirements, connected university portals, external submission, receipts and cross-system calendar. The approval screen in Figma illustrates this future boundary; it is not an active submit feature.

## Build order

1. Validate the navigation and Counselor-to-workspace handoff with students.
2. Improve source visibility and correction paths in Profile, research and application requirements.
3. Connect plan tasks, deadlines and notifications into one obvious action queue.
4. Add partner/catalog adapters only with source rights, freshness and provenance.
5. Design and implement explicit approval, submission receipt and recovery flows before any external write capability.
