# PAI Student App — Research and Design Direction (19 Oct 2026)

Goal: a student side that is clearly better than Kollegio, Appily and Common App, built for Pakistani Matric / O-level / FSc / A-level students, phone first, visual first.
Blueprint board: https://www.figma.com/board/rmqJjhkgbqK5sT7X2Wv8cJ (sections 01-12).
Note: Mobbin pattern search was not available (needs a paid plan); pattern research below comes from public sources.

## 1. What the competitors do (student side)

| | Kollegio | Appily (EAB) + Appily Match | Common App |
|---|---|---|---|
| First value | College quiz, 3 schools free, then sign-up wall | Registration form, then a 30-min Match profile | Long form sections, no early value |
| Profile | Form with completion %, "Missing details", 8 "Your story" text boxes, US-only fields (GPA/4, SAT, ZIP, ethnicity), "multiply your chances" nag | GPA, coursework, interests; "the more you fill, the more matches" | Fixed sections with character limits; core app locks after first submit |
| AI | "Ask Reka" chat bar, essay help, memory of hobbies | Marketing says AI; no student chatbot found | None |
| Documents | No student upload or extraction found | Transcript upload / school-verified; GPA converted to 4.0 | Counselors upload; students do not |
| Matching | Weekly "Made for you" list, admit rates; no clear fit scale | Reach / Target / Likely (labels inconsistent across pages) | None |
| Direct admission | Promised ("get admission offers"); flow not public | Monthly offers, "never rejections", non-binding, anonymous until student shows interest | Automatic eligibility, no opt-in; offers on dashboard + email |
| Engagement | 9-milestone "Journey" in 3 acts | Planner checklist, deadline tracker | Checklist + push reminders |
| Privacy | Policy allows paid transfer to colleges + ad partners | Calls itself a data broker; mixed signals | No explicit consent step for DA |
| Weak points | US-only, form-first, parts not joined into one picture | Offers feel like a scam to some students; offer is not fit | iOS 3.0 rating: logouts, unreadable inputs, blank tabs |

## 2. Where PAI wins (our 12 differentiators)

1. Paths first, places later. Nobody else helps a student choose WHAT to do before WHERE.
2. Value in 10 minutes: First Snapshot (interest shape, top values, 3-4 directions with traffic lights) before any long form.
3. Built for Pakistani education: boards, groups (Pre-Med, Pre-Eng, ICS, Commerce, Arts), marks out of 1100/1200, O/A-level grades, IBCC, entry tests — all as data, generic in code.
4. Photo of a result card -> fields extracted -> student confirms -> marks become "shown" (Verified badge). No competitor does this for students.
5. One living picture: chat, taps, uploads and edits feed one profile (My picture + Details + hidden PAI memory). Kollegio keeps them separate.
6. Visible, correctable memory ("What PAI knows about you"): summary, relation graph, sources, history, edit/remove.
7. Honest Path 360 view: challenges for YOU, what it will not give you, Plan B, sourced reality. Never a sales page.
8. Family is first class: family map, "whose wish", family-talk help, a parent summary card to share on WhatsApp (summary only, never the chat).
9. One clear fit scale for places: safe / realistic / stretch / not yet + route, only from shown/confirmed marks, with source + date.
10. Consent per university, per field, with preview, audit log and one-tap revoke. Anonymous until the student says "interested". Students are never sold.
11. Offers that look trustworthy (later): verified university badge, conditions, real cost after scholarship, expiry, "what this offer does NOT cover".
12. Works on cheap Android and slow internet: small JS budget, stays logged in, offline cache for saved items, queued messages.

## 3. Design rules we adopt (from the research)

Onboarding and reveal
- One question per screen, one primary button per screen, step indicator + thin progress bar.
- Big tap chips and cards; text input only when needed.
- Ending = recap card ("Here is what I heard"), then straight into the first chat.
- Results reveal as 4-6 tap-through story cards ending on a 9:16 share card (WhatsApp Status / Instagram).
- Interest result: archetype card (name + illustration + 1-line why) on top; RIASEC as horizontal bars (readable at 360 px); radar only as an optional detail.
- Every match/direction has a "Why this fits you" expander quoting 2-3 of the student's own answers.
- One celebration per milestone, never per tap.

Chat
- Typing state within 300 ms; streamed tokens; Stop button.
- 2-3 contextual reply chips after each counselor turn.
- Structured content as inline cards (path, snapshot, mirror, upload, rating, compare), max one primary action per card.
- Large mic button; Roman Urdu input welcome; UI stays English (founder decision).
- Toast "PAI noted this · View" when a fact is saved.

Documents
- Camera or gallery or PDF (marksheets live on WhatsApp).
- Quality check with live hints (blur, glare, corners), auto-capture, manual fallback.
- Review screen: image thumbnail beside extracted fields; low-confidence fields in amber with "Please check" (icon + text, never color alone); every field editable; never auto-submit.
- Real % upload bar, resumable, client-side compression (~1600 px, q 0.7).
- Privacy note at the moment of upload; option to delete the original after confirming.

Motion and performance
- Micro 100-200 ms, enter ~225 ms, exit ~195 ms, full screen 300-375 ms, never > 400 ms; ease-out in, ease-in out.
- Animate only transform and opacity. MotionConfig reducedMotion="user".
- Initial JS <= 300 KB gz (target 170 KB critical), LCP <= 2.5 s, INP <= 200 ms, CLS <= 0.1 on a mid Android.
- Skip heavy celebrations when navigator.deviceMemory <= 2.
- Touch targets >= 48 px, body text >= 16 px, contrast >= 4.5:1.

Trust (teens)
- Sharing off by default; per-recipient consent with field list, duration, revoke, sharing log.
- Explain each data use at the moment it is collected.
- Under 18: short privacy note; parent view = summary only; visible "Parent connected" badge.
- No ads, no third-party trackers; export and delete in 2 taps.
- AI transparency: "based on last season's merit, not guaranteed", source + date on every world fact.

## 4. Audit of the current build (screenshots v2, 19 Oct)

Good: design tokens and kit; profile hero with Mirror quadrants, 10-area heatmap, certainty chart, family map, education timeline; auth screens; shell with sidebar and bottom tabs.

Problems to fix
1. Onboarding shows a raw chip "Catalog level" (education catalog empty) and the field "Secondary education" — a catalog leak.
2. Chat card shows "Reviewed catalog entry" — same leak.
3. Floating "Talk to PAI" pill duplicates the mic in the composer.
4. No Home screen: the app opens on chat; no "your next step" card.
5. No First Snapshot, no interest archetype/RIASEC, no values ranking, no traffic lights anywhere.
6. Profile is still text-heavy (long quadrant sentences, chips); no PAI memory area; no Details inline edit.
7. Path page has no "challenges for you / what it will not give / Plan B / honest summary".
8. Documents screen and upload review flow not designed as a full flow.
9. Paths, path page, programs, compare, plan, documents, settings, states not yet ticked in UI_CHECKLIST.
10. Onboarding fields still name/level/city/language (needs first+last, DOB, gender, education, country+city, phone optional; no language step).

## 5. Decision

Keep the stack and the kit. Redesign the student app around: Home -> Chat -> First Snapshot -> Profile -> Paths -> Path 360 -> Compare -> Plan, with Documents, Privacy and Settings, and future Offers behind a flag.
Design reference: Figma design file "PAI Student App - UI v3" (see PLAN_DOCS_INDEX). Build prompt: docs/counselor/STUDENT_APP_V3_PROMPT.md.

## Sources
Kollegio: kollegio.ai, kollegio.ai/feature/recommendation, kollegio.ai/privacy, kollegio.ai/for-colleges; profit.pakistantoday.com.pk (Jul 2024). Appily: appily.com/match, appily.com/faqs, eab.com/appily-match-faq, NPR 27 Dec 2024, connectprep.com/direct-admissions-2026. Common App: commonapp.org Direct Admissions resources, apps.apple.com Common App reviews. Patterns: careerexplorer.com/career-test, Xello Matchmaker guide, niche.com college quiz, taplytics (Duolingo), appcues (Headspace), aiuxplayground chat playbook, OpenAI memory FAQ, Incode ID-capture guide, m1.material.io motion, motion.dev accessibility, infrequently.org performance, datareportal Pakistan 2026, StatCounter Pakistan, arXiv 1811.11983 (Roman Urdu), UK Age Appropriate Design Code, Chambers Pakistan data protection 2026.
