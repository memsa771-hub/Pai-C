# PAI C Core v1: code review against the approved core and the features to build

Date: 9 Oct. Reviewed branch `pai-c` at 479513b (`backend/app/pai_c/`, about 3,700 lines).
Approved core: FigJam 97yQ5hwTjywjMDazpqBUmc (Truth Map + adaptive loop). Later layers: vision board S27Msa6VtjNDdaysbqFWgz.
Planning document. No Codex prompts until the founder approves this spec.

## 1. Review verdict

The plumbing is strong; the brain is built for the old flow.

Keep (solid engineering, reuse as is):
- Versioned notebook with history rows, workspace locks, ordered idempotent background jobs.
- Mirror job with validation, retry, confirm/edit, MIRROR stage.
- Research gateway, light research, cached verified facts, student budgets, grounded roadmaps.
- Noted questions, usage logging, session exporter, smoke script, 631 offline tests.

Change (the parts that decide counseling quality):
1. Notebook schema does not match the Truth Map.
   - SAID and SHOWN exist (stated_goal, claims with evidence levels).
   - SOURCE is a fixed list that includes a platform-specific value ("reels"): not generic.
   - PRESSURES: family is hardcoded to father and mother; no guardians, siblings, spouse, others; no peers, status, money as pressures.
   - SURE (certainty 0-10) is missing.
   - No date, source type or confidence on most items, so the map cannot stay alive over time.
   - No tensions, identity status or decision difficulties.
   - coverage.person requires daily_life, which the approved first meeting no longer asks.
2. Analyst rewrites the WHOLE notebook every turn from up to 60 messages. Cost grows with every turn, and a bad rewrite can silently drop facts. It also does not plan the next move.
3. Counselor prompt v3.3 forces "reflect + one question, under 40 words, no advice" on every reply. This produced the interrogation in the founder test.
4. Safety depends on the Counselor model choosing action "wellbeing". There is no check before the reply.
5. No first picture, no "did PAI understand you?", no certainty before/after: we cannot measure the core.
6. No quality loop: no fixed set of real conversations to replay after each change, no automatic scoring.

## 2. Core v1 features (the "super features")

### F1. Truth Map (Notebook v2)
- Six parts: SAID, SHOWN, SOURCE, PRESSURES, SELF, SURE.
- Every item: value, evidence (quote or paraphrase), kind (said / shown / document / action), confidence (low / medium / high), first_seen, last_confirmed.
- People are a generic list: {role in the student's words, wish, concern beneath it}.
- Source categories generic: self, family, peers, media, need, other, unknown.
- SURE: score 0-10, reason, what would raise it, when asked.
- Private derived fields: tensions (between, evidence, status), identity status (explored x committed), decision difficulties (CDDQ categories with evidence).
- Coverage rewritten for the six parts and the depth modes; migrate v1 notebooks automatically.
- Done when: an old notebook migrates without losing facts; every item has a date and confidence; no hardcoded roles or platforms.

### F2. Planner (Analyst v2)
- Returns a PATCH (add / update / confirm / retire items), not the whole notebook. Code applies and validates it.
- Input: current map + rolling summary + last N turns (from config), not 60 messages.
- Output also includes the plan for the next turn: next_move (understand / tell / both), intent, which gap, playbook, and one thing to give the student.
- Tracks the first-meeting step and the first-picture moment.
- Done when: cost per turn stays flat as the conversation grows; a fact is never lost unless explicitly retired; the plan exists before the next student message.

### F3. Voice (Counselor v4)
- Short prompt: OARS moves, at most one question, reflections outnumber questions, give before you take, summary every few turns, follow the plan and the playbook, facts only from research, family without blame.
- Receives: student message, short map summary, plan, one or two playbooks, research if any.
- Repetition guard: near-duplicate question of the last five is retried once.
- Done when: on the founder's PhD conversation and the replay set, no repeated question, reflections >= questions, value at least every 3rd reply.

### F4. Playbooks
- Small data files, generic, versioned, each with its own offline test: impatient, short answers, parent speaking, sure but not explored, no idea, family conflict, failure or setback, returning after a gap, only wants facts.
- The Planner picks up to two; the Voice follows them.
- Done when: each playbook has a fixture conversation and passes the judge.

### F5. Safety gate
- A cheap check on every student message before the Voice (distress, self-harm, abuse, danger).
- Positive: wellbeing reply path (care, resources from config, no counseling task), counseling paused.
- Done when: safety fixtures always route to wellbeing; normal messages add little delay.

### F6. First meeting, first picture, Mirror v2
- First meeting order: open introduction, what he enjoys, strengths and stuck points asked indirectly, first reflection, goal (do not re-ask), clarity check (0-10, source, a normal day in that life), first picture.
- First picture: three things understood and how clear the goal looks; student corrects; corrections feed the map.
- Mirror v2: SAID vs SHOWN vs SOURCE gaps framed with respect; family concerns honoured; SURE before and after.
- After the Mirror: "Did PAI understand you?" 1-5.
- Done when: the first picture appears within the first ~10 messages in full mode, earlier in quick mode.

### F7. Quality loop
- Replay set: anonymised real conversations (founder tests first), stored as fixtures.
- Judge: a cheap model scores each session with a rubric (OARS counts, value given, repeated questions, family respect, facts without sources, mirror accuracy vs. the student's correction).
- Metrics per session in the exporter: drop-off turn, reached first picture / mirror, understood score, certainty change, cost.
- Every Core change runs the replay set offline (and one capped live smoke only when asked).
- Done when: one command produces a scorecard for the replay set.

## 3. Later (not Core v1)
- Return visits: session summary, recap on return, stale re-check (v1.1).
- Living Mirror page, 30-day test tracking, check-ins at the student's rhythm (v1.2).
- Hand-offs to PAI OS and human counselors.

## 4. Build order
0. F0 Data cleanup (ARCHITECTURE.md section 11): store ownership boundary, embeddings off, single profile block in context, legacy discovery removed (coordinate with PAI OS), generic field definitions.
1. F1 Truth Map + migration (everything depends on it).
2. F2 Planner (patches + plan).
3. F5 Safety gate (small, independent).
4. F3 Voice + F4 playbooks.
5. F6 First meeting, first picture, Mirror v2, understood score.
6. F7 Quality loop (start the replay set from day one with the founder's sessions; the judge lands with F3).
Gate for Core v1: 7 of 10 real students reach the mirror, average understood >= 4/5.
