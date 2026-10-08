# Student Profile foundation in the deep Counselor

This document describes the current boundaries and the intended evidence rules.
For implementation details and upcoming work, start with
[the Counselor index](counselor/README.md).

## One student record, one Counselor

The Profile is the student's reusable, reviewable record backed by the Vault.
Text, voice and document intake use the existing candidate/reconciliation flow;
a conversation statement must not silently become a verified credential.
There is one deep Counselor runtime, shared by chat and voice. PAI OS remains a
separate execution surface; this document does not change its behavior.

The Counselor learns about the person before making strong personalized
recommendations. Incomplete information is a reason to ask a focused question or
qualify a conclusion, not to prevent the student from speaking or correcting a
fact. This is not a mandatory document-upload gate or a claim that every profile
field must be filled before counseling starts.

## Current context and persistence

- Profile context comes from the canonical student snapshot/compact projection,
  with source labels. Known identity fields are marked "never ask" in context.
- Recent conversation supplies continuity while background persistence completes.
  Recent statements are not necessarily accepted Vault facts yet.
- The background memory extractor runs per successful human turn and submits
  candidates through the existing validated reconciliation path into the Vault.
- The background Analyst updates the private Counselor Notebook: coverage,
  claims, questions, motivations, family context and constraints. Schema/evidence
  validation and version checks protect those updates.
- The Notebook supports discovery; it is not a second Profile, a second Vault,
  or a source of verified academic credentials.

## Education, evidence and corrections

Collect current education/status, highest completed qualification and relevant
previous education in context. Do not repeatedly ask for a known qualification
just because the student is not currently enrolled. Family, experiences and
certifications can be explored as relevant rather than blocking initial access.

A student report and a document-supported fact have different provenance.
Uploaded transcripts and certificates can support a claim; extraction alone
cannot establish document authenticity, institutional recognition or admission
eligibility. Preserve the existing evidence and verification labels rather than
calling every extracted detail officially verified.

Contradictory statements should go through reconciliation and conflict review,
not silently overwrite accepted facts. Distinguish corrections from additional
qualifications using the record's identity and evidence. A second degree may be
a separate education record. Keep uncertainty visible and let students review
and correct their Profile. These are durable data rules, not topic-specific
conversation branches or guarantees that every extraction will be correct.

## Discovery and the upcoming Mirror

Notebook coverage and depth mode determine readiness for a Mirror. Readiness is
separate from credential verification or a fully populated Profile. The Mirror
job and student confirmation are not implemented yet (PR 6).

During counseling, factual research questions are stored as deferred notes;
they do not launch Operator research. PR 7 adds research cache and light research
after Mirror confirmation. PR 8 builds roadmaps from that confirmed Mirror;
deep research is reserved for the chosen roadmap. The shared research gateway
already guards delegation and preserves refreshes of existing stale roadmaps.
Existing Roadmaps still loads, but that is not the new Mirror-to-roadmaps flow.

See [Lean Counselor](counselor/LEAN_COUNSELOR.md) for the memory cadence decision
and pre-Mirror safety contract, and [local testing](COUNSELOR_LOCAL_TEST.md) for
current model settings and test scope.
