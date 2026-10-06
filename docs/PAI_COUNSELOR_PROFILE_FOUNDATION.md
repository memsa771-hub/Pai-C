# Counselor-first student profile: product and system design

Status: design proposal. This document does not claim the behavior below is implemented.

## Product contract

PAI should accept the student's goal immediately, then learn enough about the
student to give advice that is personal and defensible. The Counselor is always
available. A missing profile restricts the *strength of a recommendation* and
consequential OS actions; it must not prevent a student from talking, asking a
general question, correcting a claim, uploading a document, or exploring.

The Profile is the student's reusable, reviewable record. PAI OS is where work
is planned and carried out. Neither is a second Counselor or a second Vault.
Text, voice, profile edits, and document extraction use the existing candidate
and reconciliation path. Recent student statements can inform the current
conversation before asynchronous reconciliation, but must not be represented
as already accepted Profile facts.

## Observed failure in the supplied conversation

After the student said they wanted a bachelor's abroad and reported FSc
Pre-Engineering, 80%, Germany, English instruction, and IELTS 7.5, PAI said
they were eligible or competitive for broad sets of programs, named typical
score thresholds, and described German pathways and deadlines. It had not
established the specific intended degree, institution, intake, exact
qualification recognition, cost constraints, or an official current source.
The student had reported grades and test scores; PAI had not seen supporting
documents. The appropriate next move was to preserve the goal, mark those
claims as student-reported, clarify one decision-critical gap, and offer to
research real programs and admission routes with citations.

## Existing architecture to retain

- Identity onboarding already writes through `OnboardingService` to Vault and
  gates a fresh workspace. It currently covers identity and location, not a
  complete education or family foundation.
- `StudentUnderstandingBuilder` derives education, prior-study gaps,
  experience, goals, and provenance from the canonical snapshot.
- Conversation, voice, and documents already propose candidates; the
  reconciler decides what enters the canonical Profile.
- Education and certification records already carry `verification_status`.
  `document_supported` is not proof of document authenticity or an official
  admissions determination.
- The active `CounselorCore` currently sends a bounded student context and a
  conversational prompt to the model. It does not call the existing
  `CounselingEvaluator`/`CounselingPolicy`, enforce decision sufficiency, or
  attach researched admission sources to an ordinary turn. A prompt alone is
  therefore not the required guardrail.

## One continuous intake, not a second application form

The system should derive a profile foundation view from accepted Vault records
and the student's current conversation. Store its state as a read projection,
not as another profile or a percentage score. Every missing item has a reason,
source, and whether the current decision actually needs it.

1. **Identity:** reuse onboarding facts. Do not ask again in chat.
2. **Education backbone:** current or most recent qualification, study status,
   institution/system where relevant, subjects and results needed for the
   student's stated goal, and the immediately preceding qualification. Allow
   unknown and partial values. Multiple genuine qualifications may coexist;
   a conflicting claim about one qualification becomes a Profile issue.
3. **Direction and circumstances:** learn the student's own intended field and
   reasons, constraints, language preference, target geography, timing, and
   finances only as they become relevant to the decision.
4. **Family context:** ask a small, purpose-specific question only when family
   support, responsibilities, first-generation context, or funding affects the
   student's choice or an application. Do not copy a US-specific parent form
   into a global profile. A structured family/circumstances record would need
   consent, restricted visibility, and a separate schema before collection.
5. **Experience:** invite relevant projects, activities, work, awards, and
   certifications. Absence is not a defect; students may have responsibilities
   and opportunities that do not appear on a conventional resume.
6. **Evidence:** after recording a self-reported education, test, or
   certification claim, offer an optional upload in context. Do not repeat the
   request every turn or block ordinary counseling if the student cannot upload.

Ask at most one useful question per conversational turn. The student may start
with any goal. Answer what can responsibly be answered now, retain the goal,
and return to the most consequential missing fact. The same question must not
be asked again when the student just answered it but reconciliation is pending.

## Decision and action gates

These gates belong in backend policy and are consumed by both text and voice.
The frontend may display progress, but cannot be the authority for access.

| Situation | Allowed response/action | Required boundary |
| --- | --- | --- |
| Identity onboarded, no education yet | General explanation, exploration, document upload, student goal capture | No personal eligibility or admission verdict; ask current qualification |
| Student has reported relevant education | Provisional comparison and a useful next step | Label grades/tests as student-reported; no program-level eligibility claim |
| Goal plus relevant academic and practical context | Personalized pathway planning and targeted research | Show gaps and alternatives; distinguish advice from sourced program facts |
| Official program requirement researched | Compare *that* requirement with accepted Profile evidence | Keep source URL, program, intake, checked time, and uncertainty |
| Student document processed | Mark supported claims `document_supported` after reconciliation | Do not call the document authentic or the student admitted/eligible |
| Provider verification or partner receipt | Mark externally verified outcome only through a trusted integration | Preserve issuer, verification method, time, and receipt |
| External submission or other consequential write | Prepare and preview work | Explicit student approval, then verified receipt and recovery path |

The Counselor must not refuse useful general help just because the Profile is
incomplete. It must also not announce a personal match, guaranteed admission,
or broad country-level eligibility as a substitute for program research.

## Claim and evidence lifecycle

`student says it -> self-reported candidate -> reconciliation -> Profile fact`

`student uploads document -> extraction + document authority -> candidate ->
reconciliation -> corroborated or disputed claim`

`trusted issuer/provider check -> external verification event -> verified claim`

Keep the existing source assertion and revision trail. A transcript upload
may support the reported grade. Its presence alone does not establish that the
file is authentic. The UI should distinguish **Student-reported**, **Document
supports this**, **Externally verified**, **Needs review**, and **Expired**.
Document contradictions become Profile issues instead of overwrites. The
student may keep the current claim, accept a proposed correction, or provide a
new value through the existing resolution path.

In normal conversation, PAI should say “you told me your FSc result was 80%”
until evidence supports a stronger statement. It should never announce that a
claim is verified because an upload was merely received or parsed.

## Research and counseling response contract

For country, university, program, test, deadline, cost, recognition, or visa
claims, PAI needs a source-backed research result scoped to the student's
program and intake. General orientation may be identified as general; it must
not become a claim that the student qualifies. If a provider or official page
cannot be reached, PAI should say what remains unconfirmed and offer the next
research action. It should not send the student away with “go check yourself”
when PAI has an authorized research capability; PAI can do the research and
bring back the source and limits.

A response should typically do four things in natural language: acknowledge
the student's stated aim, reflect one relevant known fact with its evidence
level, explain what PAI can do next, and ask one decision-critical question if
needed. Avoid a long checklist, unrequested document demand, unsupported
numeric chance, or a universal country rule.

Example after the supplied student's IELTS statement:

> “IELTS 7.5 is useful for your English-taught plan. I have your FSc result and
> IELTS score as figures you told me; if you share the result documents later,
> I can attach them to your Profile. I can research actual English-taught
> German bachelor's programs and compare their current entry routes with your
> qualification. Which subject do you want me to start with?”

That example does not assume the score is currently valid, that every program
accepts it, or that FSc gives direct entry.

## Implementation sequence

1. Create one backend `ProfileFoundation` read projection from accepted Vault
   and Student Understanding. It should report only decision-relevant missing
   facts, active conflicts, and evidence levels. Add recent-turn context so
   asynchronous extraction does not cause repeated questions.
2. Connect the existing decision-sufficiency and policy machinery to the
   active `CounselorCore` turn. The policy selects whether this is orientation,
   provisional counseling, sourced comparison, or action planning. Both text
   and voice must call the same path.
3. Add a response-level check for unsupported personalized eligibility and
   unsourced program facts. A failed check triggers a natural, scoped rewrite
   or a safe answer, never an invented citation or hidden JSON.
4. Make evidence levels visible in Profile, especially for education, tests,
   and certifications. Offer contextual document upload, process the file,
   reconcile its claims, and show any disagreement in the existing issue UI.
5. Add a small, consent-aware family/circumstances schema and UI only after
   deciding the specific decisions it supports. Keep it separate from
   institution-specific application questions.
6. Connect the Counselor's research action to official-source results, with
   source, last-checked time, program/intake scope, and a student-approved
   handoff to PAI OS tasks.

## Acceptance scenarios

- A new student can state “I want to study abroad” immediately. PAI responds
  naturally and asks for current education before claiming personal fit.
- “FSc Pre-Engineering”, “I finished both parts”, and “80%” update the same
  education context across turns without repetitive questions. Before a
  supporting document, the Profile displays student-reported status.
- An IELTS 7.5 claim remains student-reported until a suitable score report
  supports it; an upload alone does not become official verification.
- PAI does not claim direct German entry, a program requirement, or a deadline
  without a current, program-scoped source. It offers to research the issue.
- A conflicting transcript raises a Profile issue and preserves the prior
  accepted fact until resolution.
- A second genuine bachelor's degree can coexist with the first. An
  ambiguous repeated qualification is reviewed rather than silently replaced.
- Text and voice yield the same gate and evidence behavior; profile and OS
  views read the same canonical claims.

## Research basis

- [Common App first-year guide](https://www.commonapp.org/apply/first-year-students/):
  shared profile sections include family, education, testing, and activities;
  individual colleges retain different requirements.
- [Common App materials guide](https://www.commonapp.org/static/b3bf7d597fc06144ea6e0ff4673eb6b2/Resource_FY_GatherMaterials_ENG_2025.06.25_1.pdf):
  self-reported scores and official reports are distinct.
- [uni-assist admission check](https://www.uni-assist.de/en/tools/check-university-admission/):
  foreign qualification recognition requires checking the actual certificate;
  its result is orientation rather than a binding admission decision.
- [NACAC ethical guidance](https://www.nacacnet.org/who-we-are/what-we-do/guiding-ethics/nacacs-guide-to-ethical-practice-in-college-admission/):
  admission guidance should be truthful, current, and transparent.
- [UNESCO guidance on generative AI in education](https://www.unesco.org/en/articles/guidance-generative-ai-education-and-research):
  human agency, privacy, and age-appropriate safeguards matter for students.
