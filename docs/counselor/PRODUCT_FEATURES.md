# PAI C product features and user flow

Date: 10 Oct. Status: proposal for founder approval. Diagrams: vision board S27Msa6VtjNDdaysbqFWgz (9 screens and data sources, 10 chapters after choosing).
Builds on: approved core (Truth Map), ARCHITECTURE.md, CORE_V1_SPEC.md.

## 1. Screens

### 1.1 Chat (home, one conversation for life)
- Text and voice in the same conversation.
- Header: "understanding" progress (from Truth Map coverage), current chapter (getting to know you / your picture / routes / your plan).
- Inline cards in the chat (not separate pages): first picture, Mirror, roadmap summary, research answer with source, Try-it, check-in, "PAI heard this, add to your profile?".
- Quick replies when the student gives short answers (two options).
- The conversation never ends; the chapter changes.

### 1.2 My Profile (CV style, verified only)
A clean CV that fills itself over time. Only true, checked things appear.

Sections: header (name, current status, location if given), Education, Tests and results, Skills, Projects and work, Activities and responsibilities (leadership, family business, volunteering, sports organising), Achievements, Languages, Documents.

Rules (what may enter the CV):
| Source | Enters the CV? | Badge |
|---|---|---|
| Document uploaded and verified (transcript, certificate) | Yes | Verified by document |
| Action proven in PAI (Try-it done, result reported with evidence) | Yes | Shown by action |
| Truth Map item at level "sustained" or "proven" with evidence | Yes, after the student confirms | Confirmed by you |
| Only said in chat ("claimed" or "tried") | No. Goes to the Pending tray | none |
| Student adds or edits manually | Yes | Self-reported |

- Pending tray: "PAI heard: you organised local cricket matches for a season. Add to your profile?" Yes / Edit / No.
- Every line can be edited or removed; changes go through the existing Vault reconciliation.
- Private things never appear in the CV: pressures, family concerns, certainty, tensions, identity status. Those live in My Picture or stay private.
- Later: export as PDF CV (execution tasks belong to PAI OS).

### 1.3 My Picture (living mirror)
- The latest confirmed Mirror: SAID vs SHOWN, where the goal comes from, pressures with respect, strengths, limits, certainty.
- "How I changed": short history of certainty and key changes over time.
- "Correct me" opens the chat with the correction.

### 1.4 Roadmaps
- 4-5 cards from the confirmed Mirror: why it fits you, strengths used, what it protects you from, family fit, gaps (need / have / gap), Try-it, sourced facts with verified or unconfirmed labels.
- Compare, favourite, dismiss, add my own, choose.

### 1.5 My Plan (after choosing)
- Chosen route as a timeline: current step, next step, Try-it with its measurable result, milestones, outcomes log (test scores, applications, results).
- Next check-in date and rhythm (student sets it; easy to pause).
- Execution items (applications, documents, deadlines as tasks) hand off to PAI OS.

### 1.6 Documents
- Upload; extraction proposes facts; verified facts move into My Profile with the "Verified by document" badge.


## 2. How the conversation flows

Chapter 1, getting to know you: first meeting order (introduction, what he enjoys, strengths and stuck points indirectly, first reflection, goal, clarity check), first picture around message 10, then deeper discovery until the map is clear.

Chapter 2, your picture: Mirror card; confirm or edit; "did PAI understand you?" 1-5; certainty after.

Chapter 3, routes: light research, roadmap cards, discussion in chat, choice.

Chapter 4, your plan (coach mode): commit to the Try-it, check-ins on his own commitments, review the test (fits / does not fit), executing steps with PAI OS, outcomes, setbacks with care, life changes update the map, route change goes back to roadmaps.

Chapter 5, next stage: school to university to work; same relationship, new question; the map carries over with dates and re-checks.

At any time: the student can ask anything; factual questions are noted and answered with sources; distress goes to the wellbeing path; returning after a gap starts with a recap and "what changed?".

## 3. What exists today vs what is new

| Feature | Today | Needed |
|---|---|---|
| Chat with voice | Exists | Header progress, new inline cards, quick replies |
| Profile with verification badges | Exists (Vault records, verification) | CV layout, Pending tray, Truth Map items as source, hide private parts |
| Mirror card | Exists | Mirror v2 content, understood rating, My Picture page with history |
| Roadmaps | Exists | Minor: link to My Plan |
| My Plan | Not built (choice and stage exist) | Timeline, Try-it tracker, check-ins, outcomes log |
| Documents | Exists | Feed CV with badge |
| Privacy | Partial | One page: see, correct, delete, download |

## 4. Order
1. Core v1 (Truth Map, Planner, Safety, Voice, playbooks, first picture, Mirror v2, quality loop).
2. CV-style Profile with Pending tray (uses Truth Map and Vault; high value, mostly frontend).
3. My Picture page.
4. My Plan + Try-it + check-ins (coach mode).
5. Privacy page, PDF CV, PAI OS hand-off.

## 5. Update 10 Oct (founder feedback)

- Privacy page is out of scope for now. Focus: PAI C only, simple and attractive UX.
- The "30-day test" is replaced by **Try-it** (career prototyping, Burnett and Evans; Ibarra's career experiments; job shadowing evidence from OECD):
  - Purpose: learn how a route feels before or after choosing, not to prove anything.
  - Two kinds: Talk to someone in it (short conversation; PAI prepares three questions) or Taste the real work (a tiny task linked to the student's own life, a free intro lesson, shadowing a day).
  - Size from an hour to a few evenings; the student picks one or skips; no fixed 30 days.
  - After: one tap "how did it feel" (I want more / okay / not for me) and one line "best part, what drained you". This updates SHOWN and SURE; a real result can be added to the profile as "Shown by action".
  - Suggestions are generic and come from the student's own context; where-to-find details come from research with sources.
- Profile design (Design canvas "PAI C Profile and Try-it"): summary card with headline written only from confirmed items, profile strength (Starting / Growing / Strong, based on verified items, with one next step), "New from your chats" cards with Add / Edit / Not true, sections as cards (Education, Projects and work, Activities and responsibilities, Languages, Skills chips, Achievements with an upload empty state), a proof icon on every line (document / shown by action / confirmed by you) that opens "Why is this here" (source, proof, the student's words, how to make it stronger, edit, remove). One CV PDF button.
