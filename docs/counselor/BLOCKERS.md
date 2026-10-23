# Build blockers

No live provider verification is permitted in this build. All reported behavior
is verified with offline providers; real-world source coverage and conversation
quality require a separately approved evaluation.

The board supplies a small entry-level catalog, now implemented as data. Authoritative board/subject catalogs have not been supplied. Factual cards use
the approved editable-text/upload fallback until reviewed data packs exist.

No authoritative seasonal entry/merit packs are provided. The data contract and
expiry checks are implemented, but no real eligibility threshold is seeded.
Safe/realistic/stretch labels must remain unavailable without reviewed rules.

The deterministic grounding guard validates declared world claims and numeric
claims. An unannotated qualitative assertion can evade deterministic detection;
the prompt prohibits it, but this is not a proof of semantic truth. No live
quality evaluation has been run. Program assertions are separately sourced and
validated; generic explanatory prose remains a model-quality limitation.

## Reviewed career sources
No reviewed occupational-source domain pack is supplied. The path workflow performs existing SourceVerifier checks but will not label unreviewed sources verified. General path explanations remain available; sourced myths/jobs/outlook show missing information until authoritative sources are configured. This is deliberately not replaced by model guesses. Semantic institution-name absence in general prose still needs a quality evaluation; no live call was authorized.

## Seasonal merit data and record matching
No reviewed seasonal entry/merit data was supplied. Safe/realistic/stretch therefore remain unknown unless verified program+season rules exist; minimum entry eligibility is separate. Record comparisons use exact canonical identities. Ambiguous record identities or mismatched units need reviewed mapping and remain unknown; the implementation does not guess equivalences or calculate admission probabilities.


## Joint OS contract (board 11 / contract.intake)
The locked board requires both developers to sign off on versioned contract changes and tests on both sides. This run is expressly forbidden to change pai-os or shared KEEP behavior. Existing decision records, student requests, escalations/service token and named jobs remain tested and intact. New OS outcome intake, typed requests/answer events, chosen path/place fields and execution-summary extensions are not enabled. Checked the existing contract and audit; did not create a parallel intake or infer a remote schema. This is the handoff for joint implementation, not a reason to stop the Counselor work.

## Founder verification limits
The browser flow uses real components with synthetic, network-blocked adapters, including explicit Mirror feedback and the existing choice-token dialog. It is not a live Supabase/WebRTC/provider test. No production conversation quality, institutional search coverage, microphone, upload/OCR provider, or paid health check was exercised. Existing offline route/security/document/voice tests remain.
No university-sharing interface is enabled in the new shell. A later institution-sharing flow must present exact data and obtain per-institution consent; generic file sharing remains a separately authorized shared feature, not institutional consent.
Health thresholds now enqueue a deduplicated daily alert through the existing workspace notification service. Delivery depends on the existing worker/session sweep running; there is no new external notification channel or provider ping.

## Core continuation verification limits

The five requested engineering items are implemented. Extensive new feature testing is deferred as instructed; the existing suites, import check and synthetic browser flow are retained. Real provider/source coverage, delayed delivery on a deployed worker and live conversation quality have not been exercised.

Myth correction requires an existing official registry domain or a reviewed trusted-domain entry in `policy/myths.json`. Without one the safe result is a saved question, not a correction. Exact source quotation prevents invented paraphrases but cannot prove semantic relevance to every belief; that remains a quality-review item. The source prompt and existing policy are not a complete semantic detector of institution names in unstructured prose.

Guided family preparation intentionally requires completed stage-H results for the chosen path. Earlier family discussion stays in chat; legacy choices without H proof cannot produce a potentially institution-bearing preparation. A person without a recorded concern or a path without student evidence is shown the missing-information state. No concern or evidence is invented.

New check-ins are scheduled by new explicit choices/try-it acceptance only; existing historical choices are not backfilled. Continued care defers an unrelated follow-up. The in-app notification service retains its workspace visibility rules; separate cross-workspace operator/admin alert routing was not introduced.

## UI redesign v2 (20 October)

- **No live run.** Every screen was verified offline with synthetic fixtures and blocked network (build, unit tests, harness, crawler, flow). The Docker stack was not started, so real data shapes, long real names, real documents and provider latency have not been seen on the new UI.
- **Shared OS screens are only re-tokenised.** The Documents file manager internals (`components/files/*`) and the workspace settings sub-pages (`/[workspace]/settings/*`, reached from Settings) are shared with PAI OS. They pick up the new tokens and the student-facing wrapper, but were not redesigned, to avoid changing another developer's screens.
- **Stage chip is an approximation.** Without a backend A-K field, the chip reflects the furthest signal reached (see DECISIONS). A student who skips ahead (for example chooses a route early) shows the later stage.
- **Eligibility pills depend on reviewed packs.** As before, no authoritative entry or merit packs exist. Programs therefore show "Needs checking" unless the backend supplies a reviewed label.
- **Font coverage.** The self-hosted font covers Latin and Latin-ext (English and Roman Urdu). Urdu script, if ever shown, falls back to the system font.
- **Follow-up brief not started.** `docs/counselor/PROFILE_ONBOARDING_PROMPT.md` (new onboarding fields, editable profile, PAI memory area) says to start only after this redesign. It is untracked and was not acted on.

## Email/Google-only auth (20 October)

- Sign-in moved to Firebase Auth on 23 October; its console setup (Email/Password and Google on, authorized domains, service account) is in `docs/AUTH_SESSION.md`.
- Students who used to sign in with a username now sign in with their email. That email is the one on their account, and "Forgot password?" works as before.
