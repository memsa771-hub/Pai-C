# Beta conversation spec (29 Oct 2026)

Founder decisions for the beta launch, on top of the four features (`FOUR_FEATURES_SPEC.md`):
1. PAI drives the conversation. It opens with "tell me about yourself", draws the student out with a reflective
   question bank, then counsels with empathy and always says what comes next. The student never has to say
   "ok, next".
2. From the first message PAI knows every onboarding fact. Chat is never blank.
3. Chat uses Claude (Anthropic API, Sonnet 5.5). Extraction, classification and analysis stay on cheap OpenAI
   models; research runs use a strong OpenAI model. Total model spend is capped at $100 per month.
4. The path, Mirror and roadmap engines use tools and research so their output fits the student's profile.
5. Pakistan-wide education data: every board, O-level and A-level, not Lahore only.
6. A student can ask how PAI works and get a true answer.
7. Language is generic: PAI replies in whatever language and script the student writes; nothing in code assumes
   Urdu. The Vault stays in English.
8. Nothing broken: every feature verified end to end before the beta.

Product rules stay: education first; no fact about the student without evidence; no world fact without a
source; at most one question per reply; no praise, no lectures; no university names before stage H.

## 1. Models, providers and the cap

### 1.1 Providers per role
`inference/gateway.py` gains a provider layer. Each role resolves `(provider, model, api_key, base_url)` from
`pai_c/policy/model_roles.json` (defaults) overridden by env: `PAI_<ROLE>_PROVIDER` (`openai` | `anthropic`),
`PAI_<ROLE>_MODEL`, and per-provider keys `PAI_API_KEY` (OpenAI) and `ANTHROPIC_API_KEY`.
- `counselor` (chat reply, opening) → `anthropic`, `claude-sonnet-5-5`.
- `classifier`, `extractor`, `document_extractor`, `safety`, `summarizer` → `openai`, `gpt-5-mini` (as today).
- `analyst` (path analyzer, insight) and `mirror` (Mirror text) → `openai`, `gpt-5`.
- new `researcher` (field research, path explain, program search, rules refresh) → `openai`, `gpt-5`.
- `embeddings` as today.
`inference/anthropic_client.py` implements the same `complete()` contract with the `anthropic` SDK (Messages
API): system prompt, messages, `max_tokens`, temperature; `response_format json_object` becomes an instruction
plus the existing JSON parse-and-retry; no reasoning_effort; tools unsupported for this role (raise early).
Usage (input, output, cached tokens) is recorded the same way as OpenAI.

### 1.2 One monthly cap for everything
`inference/usage.py` records every model call's estimated USD (tokens × rate from
`pai_c/policy/model_costs.json`, per model, with a default) in `pai_usage_months` under scope `models`, plus
embeddings as today. `PAI_MONTHLY_CAP_USD` (default 100). Priorities, in data:
- at 80 % of the cap: `researcher`, `analyst` (path analysis), `mirror` text and rules refresh stop (quiet
  skip, logged once a day);
- at 100 %: the counselor reply falls back to the fixed `PAI_COUNSELOR_FALLBACK_REPLY` and tells the student PAI
  is paused for the month; extraction stops.
`GET /v1/admin/usage` (founder-only, existing auth) shows the month's spend per role.

### 1.3 Env
`.env` gains (names only; the founder fills values): `ANTHROPIC_API_KEY`, `PAI_COUNSELOR_PROVIDER=anthropic`,
`PAI_COUNSELOR_MODEL=claude-sonnet-5-5`, `PAI_RESEARCHER_MODEL=gpt-5`, `PAI_ANALYST_MODEL=gpt-5`,
`PAI_MIRROR_MODEL=gpt-5`, `MEMORY_EMBEDDING_API_KEY=`, `PAI_SEMANTIC_RECALL_ENABLED=true`,
`PAI_MONTHLY_CAP_USD=100`. Existing lines are never changed or printed. `.env.example` mirrors the names.

## 2. The conversation

### 2.1 Opening knows the student
The opening job's context includes the Vault core: name, level and group (education line as the Mirror shows
it), status, city, and any onboarding facts. `policy/actions/opening.md` tells the model to greet by name, show
in one line that it already knows where they stand ("FSc Pre-Engineering, Lahore"), and ask one open question:
tell me about yourself. It never asks what onboarding already answered. Language: the onboarding language if
known (the student's chosen app language or the language of any free-text answer), else English.

### 2.2 Question bank (data)
`pai_c/policy/question_bank.json`: ordered reflective prompts, each `{id, area, vault_types, intent_key,
prompt_key}` with the copy in the same file (English; the Writer renders it in the student's language):
1. about_you (open), 2. hobbies (unusual interests), 3. accomplishments (achievements or awards that matter),
4. extracurriculars (activities they are proud of, their role), 5. obstacles (challenges that shaped them),
6. identity (background, culture, identity: obstacles and opportunities), 7. character (how friends describe
them), 8. values (principles or causes), 9. more (anything else important).
Each maps to Vault types (interest, achievement, activity, pressure, daily_life, strength, value) so the
extractor files the answers and completeness rises.

### 2.3 Director: PAI drives
New guided-table moves, in this order after `care` and `answer`: `intro` (first exchange), `bank_question`
(the next bank item not yet asked and whose Vault types are still empty; at most one per reply; skipped when
the student's last message already covered it), then the existing basics flow (`explore_area` from the
completeness unknowns), then `counsel`.
- **Drive rule:** every reply ends with the next step: one question, or one concrete action ("Roadmap page par
  tumhare 3 fields aa gaye, kholo"). Exceptions: `care`, and a student who says stop. Enforced after writing:
  a reply with no question and no next-step line is rewritten once with `policy/prompts/drive_retry.md`, then
  gets a data-driven next-step line appended (`policy/next_steps.json`, keyed by phase).
- **Empathy without praise:** `voice_guided.md` gains a short empathy rule (acknowledge the feeling in a
  clause, then move), the banned-praise list stays.
- **No repeats:** bank items log their `intent_key` in the turn decision; asked items are never asked again.
- `questions_in_last_two` no longer blocks a bank question or the drive line.

### 2.4 How PAI works
Classifier request kind `about_pai`. Action `about_pai` answers from `pai_c/policy/about_pai.json` (data: what
PAI is, the four features in one line each, what happens to the student's words, how paths and roadmaps are
made, what PAI will not do), 2–4 sentences, and may add `show_place`. The grounding guard treats
`<about_pai>` as an allowed source.

### 2.5 Language
- The classifier returns `language` (`{code, script}`) each turn; it is stored on the workspace
  (`chat_language`) and used by the opening, the Writer, the Mirror text and chat-posted messages
  (paths found, needs education), so every message to the student is in their language.
- `PAI_LANGUAGE_BLOCKED_SCRIPTS` stays a config list; the replacement is "the student's own language" (no
  Roman Urdu default in code). Examples in prompts are language-neutral or marked as examples only.
- The Vault, Mirror card labels and engines stay English; chat-posted texts are rendered in `chat_language`.

## 3. Engines with research

### 3.1 Field research (shared, cached)
`pai_c/paths/field_research.py` + job `counselor.field_research`: for a study field (and the student's country),
one bounded research run (`researcher` role; web.search + web.fetch through the existing budget) produces a
`FieldNote` with sources: what you study, a work day, entry in Pakistan, jobs and demand, common myths. Cached
in `pai_field_notes` (migration 123) per field key, refreshed after `PAI_FIELD_NOTE_DAYS` (90). The path
analyzer and path explain read the note; the analyzer's `why` can cite the note's facts with sources. Cost is
per field, not per student.

### 3.2 Analyzer and Mirror text on strong models
The path analyzer (`analyst`) and the Mirror text (`mirror`) use the configured strong model; prompts unchanged
except the analyzer's `<field_notes>` block.

### 3.3 Rules and calendar refresh
Job `counselor.rules_refresh` (monthly, `researcher`): for each admission rule and calendar event, search the
official source, extract the current value with a quote, and write a proposal file
`backend/app/pai_c/policy/refresh_proposals/<date>.json` (diffs with sources). Nothing is applied
automatically; `scripts/apply_refresh.py` applies a reviewed proposal. Budget: `PAI_RULES_REFRESH_MAX_CALLS`.

## 4. Pakistan-wide calendar
`academic_calendar.json` gains the researched `regions` block (Punjab, Sindh, KP, Balochistan, FBISE, AKU-EB,
AJK, Gilgit-Baltistan) with per-region events and confidence. The timeline picks the student's region from
their education record's board (catalog `boards`), else the province of their city, else federal; the basis
names the region and confidence. Cambridge O/A-level sessions and IBCC lag are used for A-level students.
Secondary-sourced dates show "Dates: secondary source" as today.

## 5. Extraction quality
A golden set `backend/tests/fixtures/extraction/*.json` (student messages in Roman Urdu, Urdu and English with
the expected Vault entries: education with marks, interests, strengths, family wish, budget band, mobility,
goal, obstacles). Fake-model tests pin the normalizer and reconciler. A live evaluation script
`scripts/eval_extraction.py` runs the golden set against the real extractor with a $5 cap and reports recall and
precision; the beta bar is recall ≥ 90 % on core facts.

## 6. Verification before beta
- All suites green; Postgres migrations round trip.
- A scripted end-to-end run with real models (cap $5) on the local stack: sign-up → onboarding → first PAI
  message names the student's education → 6 chat turns in Roman Urdu answering bank questions → Vault fills
  (badges, no raw codes) → Mirror ready and redrawn → paths with Vault-cited reasons and field notes → roadmap
  steps coloured with region dates → choose → CHOSEN; "how does PAI work?" answered; an English student gets
  English.
- Known limits recorded in BUILD_REPORT_V1.md.
