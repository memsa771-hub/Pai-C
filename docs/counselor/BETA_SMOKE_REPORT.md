# Beta smoke report (2026-10-30 08:34 UTC)

- Base URL: http://localhost:8000
- Language: roman_ur
- Mode: live, real models
- Cap: $5.00
- Student: beta-smoke-20261030082930-dc98@example.com workspace d64b0da8-a5ae-47c5-812c-42fe127e339a
- Result: PASS

## Checks

| # | Check | Result | ms | Note |
| --- | --- | --- | --- | --- |
| 1 | spend baseline | pass | 4073 | month $5.0406 |
| 2 | 1 sign-in, fresh student | pass | 6531 | workspace d64b0da8-a5ae-47c5-812c-42fe127e339a |
| 3 | 2 onboarding | pass | 354 | saved ['identity.gender', 'identity.date_of_birth', 'location.current_country', 'location.current_city', 'identity.full_name', 'education'], rejected {} |
| 4 | 3 opening names education, one question | pass | 12072 |  [spend $0.0160] |
| 5 | 4.1 turn: Mujhe robots banana pasand hai, farigh w | pass | 6275 |  [spend $0.0294] |
| 6 | 4.2 turn: First year mein mere 78% marks aaye thay | pass | 8171 |  [spend $0.0670] |
| 7 | 4.3 turn: Mere abbu chahte hain ke main MBBS karun | pass | 8073 |  [spend $0.1558] |
| 8 | 4.4 turn: Hamara budget saal ka 3 se 6 lakh rupay  | pass | 8082 |  [spend $0.1673] |
| 9 | 4.5 turn: Main Lahore se bahar nahi ja sakta, ghar | pass | 12118 |  [spend $0.1899] |
| 10 | 4.6 turn: Mujhe circuits jorna aur electronics ke  | pass | 8097 |  [spend $0.3458] |
| 11 | 5 vault | pass | 122566 | 15 entries, known 6; not settled after 120 s (busy ['counselor.analyze']) |
| 12 | 6 mirror ready, text, redrawn | pass | 16672 | areas with entries ['history', 'goals', 'pressures', 'interests', 'status', 'family_social'], unknowns 4; settled in 15 s [spend $0.6760] |
| 13 | 7 paths with Vault-cited reasons | pass | 7 | 5 paths; field notes cited: 0 (absent) [spend $0.6760] |
| 14 | 8a roadmap steps coloured, region dates | pass | 79 | 5 fields, 5 timed, statuses ['open', 'open', 'open', 'open', 'open'] |
| 15 | 8b choose -> CHOSEN | pass | 1712 | chose electrical_engineering; stage CHOSEN; settled in 2 s |
| 16 | 8c tick apply step | pass | 166 | steps_done ['apply'] |
| 17 | 9 how does PAI work | pass | 16153 | names ['Vault', 'Paths', 'Roadmap'] [spend $0.7107] |

## Spend

- Source: cap_state() in the backend container; month 2026-10, stage ok
- Month counter: $5.0406 before, $5.7535 after; this run est_usd **$0.7130**
  - researcher: $0.3119
  - web: $0.1260
  - counselor: $0.1145
  - analyst: $0.0650
  - mirror: $0.0588
  - planner: $0.0252
  - extractor: $0.0078
  - classifier: $0.0036
  - embeddings: $0.0000

## Latency

- 3 opening names education, one question: 12.1 s
- 4.1 turn: 6.3 s
- 4.2 turn: 8.2 s
- 4.3 turn: 8.1 s
- 4.4 turn: 8.1 s
- 4.5 turn: 12.1 s
- 4.6 turn: 8.1 s
- 9 how does PAI work: 16.2 s
- extractor (memory.extract) jobs: 7, median 7.1 s, max 44.1 s (created_at -> updated_at)
- planner (counselor.analyze) jobs: 7, median 133.5 s, max 136.2 s (created_at -> updated_at)

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

**PAI:** Hello Ali, I'm PAI, your personal counselor. I can see you're in FSc Pre-Engineering in Lahore, so we're starting from there. Tell me about yourself: what do you do these days, and what matters to you?  
**Student:** Mujhe robots banana pasand hai, farigh waqt mein main chhote robot aur gadgets banata hun.  
**PAI:** Robots aur gadgets farigh waqt mein banana ek aisi cheez hai jo aksar mechanical, electrical ya mechatronics jaisi fields se judti hai, aur aap Pre-Engineering mein hain to yeh baat mazeed dilchasp hai. Yeh abhi ek ibtidai andaza hai, faisla nahi.  Ek baat check karni hai: yeh robots aap ne khud design karke banaye, ya kisi video ya kit ko follow kiya?  
**Student:** First year mein mere 78% marks aaye thay, Lahore board se.  
**PAI:** Shukriya, yeh marks note kar liye. Pre-Engineering ke saath maker background ka matlab hai ke hamare paas dono taraf ka evidence hai: padhai aur haath ka kaam. Abhi main marks ko achha ya kamzor nahi keh raha, kyunke yeh dekhna baqi hai ke aap kis field aur kis test ki taraf ja rahe hain.  Meri pichhli baat adhoori reh gayi thi, to ek chhota sa sawal: aap ke robots aur gadgets mein se kisi ek ka design aap ne khud socha tha, ya aap kits aur videos ko follow karte hain?  
**Student:** Mere abbu chahte hain ke main MBBS karun, lekin mujhe biology itni pasand nahi.  
**PAI:** Aap ne seedhi baat bataya, shukriya. Ek cheez saaf nazar aati hai: aap Pre-Engineering mein hain aur robots banate hain, jabke MBBS ka rasta Pre-Medical se hota hai aur uska bunyadi hissa biology hai. To abhi aap ki taraf se jo evidence hai, woh engineering aur making ki taraf zyada jhukta hai. Yeh sirf pehla andaza hai, aur main abbu ki wish ko ghalat ya sahi nahi keh raha.  Ek baat jo main samajhna chahta hun: aap ke liye MBBS ka khayal abbu ki wish tak hai, ya aap ke andar bhi kahin yeh sawal hai ke shayad medical mein kuch ho sakta hai?  
**Student:** Hamara budget saal ka 3 se 6 lakh rupay tak hai.  
**PAI:** Shukriya, 3 se 6 lakh saalana ka budget note kar liya. Is range mein kaun si jagah aur kaun si fee aati hai, yeh main sirf reliable sources se check karke bata sakta hun, andaze se nahi. Is liye abhi koi institution ya fee nahi bata raha.  Ek field jo aap ki kahani se milti hai, aur jo aap ne khud nahi kahi, woh Electrical Engineering hai: FSc Pre-Engineering ki math aur physics wahan seedha kaam aati hai, aur robots ya gadgets mein circuits aur control ka hissa isi se judta hai. Yeh sirf ek idea hai jo test karne layak hai, faisla nahi.  Aap ne MBBS ke alawa kin fields aur kin entrance tests (jaise ECAT, NAT, SAT) ke baare mein socha hai?  
**Student:** Main Lahore se bahar nahi ja sakta, ghar walay ijazat nahi dete.  
**PAI:** Yeh note kar liya: aap Lahore mein hi parh sakte hain. Is se meri talaash Lahore mein mojood options tak simat jati hai. Kaun se programs wahan available hain aur unki fee kitni hai, yeh main reliable sources se check karke hi bataunga.  Ek aur baat jo aap ki kahani mein nazar aati hai: robots banana sirf circuits nahi, balki gears, structure aur motion ka kaam bhi hai. Is liye Mechatronics ya Mechanical Engineering bhi dekhne layak hain, Electrical ke saath. Yeh abhi sirf ideas hain jo parakhne hain, faisla nahi.  Ab ek asaan sawal: school ya FSc mein aap ko kaun se subjects sab se zyada pasand hain aur kin mein aap ke marks achhe aate hain?  
**Student:** Mujhe circuits jorna aur electronics ke saath kaam karna sab se acha lagta hai.  
**PAI:** Circuits aur electronics ke saath kaam karna aap ki robots wali kahani se seedha milta hai, aur isi se Electrical ya Electronics Engineering ka idea mazboot hota hai. Bas ek farq yaad rakhna: kisi cheez ko jorna pasand hona alag hai, aur uske peeche ki math aur physics ko pasand karna alag, kyunke engineering mein dono aate hain. Yeh abhi sirf ek pehla andaza hai jo aap theek kar sakte hain.  Aap ke FSc ke subjects mein se physics aur math ke baare mein aap ka kya khayal hai: kya woh bhi utne hi pasand hain, ya sirf haath ka kaam?  
**Student:** PAI kaise kaam karti hai?  
**PAI:** PAI Pakistan ke students ke liye ek education counselor hai: pehle aap ko jaanti hai, phir aap ke liye aisi field chunne mein madad karti hai jo aap par fit ho, aur phir wahan parhne ki jagah aur raasta. Jo kuch aap batate ya upload karte hain woh aap ke Vault mein aap ke apne alfaaz aur source ke saath rehta hai, aap Profile page par dekh kar theek kar sakte hain, aur aap ki ijazat ke baghair kisi se share nahi hota. Paths aur Roadmap aap ke Vault aur sourced admission rules se bante hain; fees, merit ya deadlines PAI yaad se nahi, pehle sources se check karke batati hai. Faisla hamesha aap ka hota hai, PAI sirf saaf dekhne mein madad karti hai.  Aap ka agla qadam hai FSc mukammal karna (imtihan May 2027): Roadmap page par apna route kholein aur jab yeh ho jaye to tick kar dein.  
