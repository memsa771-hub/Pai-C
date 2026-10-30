# Beta smoke report (2026-10-30 08:38 UTC)

- Base URL: http://localhost:8000
- Language: en
- Mode: live, real models
- Cap: $5.00
- Student: beta-smoke-20261030083405-10bf@example.com workspace ffbb458b-da21-40d5-9448-5ca259039d72
- Result: PASS

## Checks

| # | Check | Result | ms | Note |
| --- | --- | --- | --- | --- |
| 1 | spend baseline | pass | 3907 | month $5.7535 |
| 2 | 1 sign-in, fresh student | pass | 5303 | workspace ffbb458b-da21-40d5-9448-5ca259039d72 |
| 3 | 2 onboarding | pass | 183 | saved ['identity.gender', 'identity.date_of_birth', 'location.current_country', 'location.current_city', 'identity.full_name', 'education'], rejected {} |
| 4 | 3 opening names education, one question | pass | 6038 |  [spend $0.0143] |
| 5 | 4.1 turn: In my free time I like building small ro | pass | 4067 |  [spend $0.0401] |
| 6 | 4.2 turn: I got 78% in first year, from the Lahore | pass | 4084 |  [spend $0.0516] |
| 7 | 4.3 turn: My father wants me to do MBBS, but I don | pass | 6090 |  [spend $0.0656] |
| 8 | 4.4 turn: Our budget is 3 to 6 lakh rupees a year. | pass | 8103 |  [spend $0.1238] |
| 9 | 4.5 turn: I can't leave Lahore, my family won't al | pass | 6090 |  [spend $0.1438] |
| 10 | 4.6 turn: What I enjoy most is wiring circuits and | pass | 6145 |  [spend $0.1539] |
| 11 | 5 vault | pass | 123578 | 14 entries, known 6; not settled after 121 s (busy ['counselor.paths']) |
| 12 | 6 mirror ready, text, redrawn | pass | 36000 | areas with entries ['history', 'goals', 'pressures', 'interests', 'status', 'family_social'], unknowns 4; settled in 34 s [spend $0.2800] |
| 13 | 7 paths with Vault-cited reasons | pass | 7 | 5 paths; field notes cited: 0 (absent) [spend $0.2800] |
| 14 | 8a roadmap steps coloured, region dates | pass | 64 | 5 fields, 5 timed, statuses ['open', 'open', 'open', 'open', 'open'] |
| 15 | 8b choose -> CHOSEN | pass | 1736 | chose mechatronics_engineering; stage CHOSEN; settled in 2 s |
| 16 | 8c tick apply step | pass | 169 | steps_done ['apply'] |
| 17 | 9 how does PAI work | pass | 10157 | names ['Vault', 'Roadmap'] [spend $0.3079] |

## Spend

- Source: cap_state() in the backend container; month 2026-10, stage ok
- Month counter: $5.7535 before, $6.0614 after; this run est_usd **$0.3079**
  - analyst: $0.1357
  - counselor: $0.0857
  - mirror: $0.0575
  - planner: $0.0196
  - extractor: $0.0058
  - classifier: $0.0035
  - embeddings: $0.0000

## Latency

- 3 opening names education, one question: 6.0 s
- 4.1 turn: 4.1 s
- 4.2 turn: 4.1 s
- 4.3 turn: 6.1 s
- 4.4 turn: 8.1 s
- 4.5 turn: 6.1 s
- 4.6 turn: 6.1 s
- 9 how does PAI work: 10.2 s
- extractor (memory.extract) jobs: 7, median 3.0 s, max 4.1 s (created_at -> updated_at)
- planner (counselor.analyze) jobs: 7, median 96.0 s, max 107.4 s (created_at -> updated_at)

## Models per role (as resolved)

| Role | Provider | Model |
| --- | --- | --- |
| analyst | openai | gpt-5 |
| classifier | openai | gpt-5-mini |
| counselor | anthropic | claude-sonnet-5-5 |
| document_extractor | openai | gpt-5-mini |
| embeddings | openai | text-embedding-3-small |
| extractor | openai | gpt-5-mini |
| mirror | openai | gpt-5 |
| ocr | openai | gpt-5-mini |
| operator | openai | gpt-5.4-mini |
| path_explain | openai | gpt-5 |
| planner | openai | gpt-5-mini |
| research_extract | openai | gpt-5 |
| researcher | openai | gpt-5 |
| router | openai | gpt-5-mini |
| safety | openai | gpt-5-mini |
| sensitive | openai | gpt-5-mini |
| summarizer | openai | gpt-5-mini |

## Defects

- none

## Transcript

**PAI:** Hello Ali, I'm PAI, your personal counselor. I can see you're in FSc Pre-Engineering in Lahore, so we can start from there. Tell me about yourself: what do you do these days, and what matters to you?  
**Student:** In my free time I like building small robots and gadgets.  
**PAI:** Building things with your hands in your free time is a useful clue, since it points toward fields like mechatronics, electrical or computer engineering, though that's only an idea to test for now. Is there something you've built or achieved, an award, a result or a project, that really matters to you?  
**Student:** I got 78% in first year, from the Lahore board.  
**PAI:** That's a useful marks anchor: 78% in first year, with second year still ahead of you. I don't have your subject-wise marks yet, so I can't say which subjects carry that number. Are you thinking about an engineering entrance test, and which fields or tests are you considering so far?  
**Student:** My father wants me to do MBBS, but I don't really like biology.  
**PAI:** Your father's wish and your dislike of biology are two different things, and it's good to see them separately. MBBS is a medical degree, and your Pre-Engineering group doesn't include biology, so I'd want to check what the actual route to it looks like before we weigh it as an option. For now, I'll treat it as your father's wish, and I'm not assuming how he feels or how strongly. In your own words, what do you want to study, and how sure are you of it?  
**Student:** Our budget is 3 to 6 lakh rupees a year.  
**PAI:** A budget of 3 to 6 lakh rupees a year is a real constraint, and it will shape which places make sense later, so I'll keep it in view. I can't tell you yet what any specific program costs or whether it fits inside that range. I'll check that from reliable sources once we have fields to compare. Your Mirror card is ready and appears right after this message, showing what I know about you and what is still unknown.  Your Profile page shows what I know about you so far; tell me more about yourself whenever you like.  
**Student:** I can't leave Lahore, my family won't allow it.  
**PAI:** Staying in Lahore is a clear limit, and it narrows where we can look. Combined with your robotics projects and your Pre-Engineering studies, one direction that may fit is Mechatronics Engineering, which mixes mechanics and electronics, much like what you already do with robots and gadgets. It's only an idea to test, and you're free to say no to it. Does it sound like something you'd want to explore, or do you have another field in mind?  
**Student:** What I enjoy most is wiring circuits and working with electronics.  
**PAI:** Wiring circuits and working with electronics points toward electrical or electronic engineering, and it sits close to the mechatronics idea we just discussed. That's a lead to test, not a conclusion. Did you work out your circuits yourself, say by designing them or fixing faults when they didn't work, or have you mostly followed videos and kits so far?  
**Student:** How does PAI work?  
**PAI:** PAI is an education counselor for students in Pakistan. It gets to know you first, then helps you choose a field of study that fits you, and then a place and a route to study it. Everything you tell me goes into your Vault with your own words as evidence, and you can check and correct it on the Profile page; it isn't shared with anyone without your permission. I don't make decisions for you, and I don't state fees, merit or deadlines from memory, I check them from sources first.  Your next step is Finish FSc (exam May 2027): open your route on the Roadmap page and tick it off when it is done.  Your next step is Finish FSc (exam May 2027): open your route on the Roadmap page and tick it off when it is done.  
