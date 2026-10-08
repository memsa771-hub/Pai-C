# PR 15: live model matrix with counselor v3.1

Eight identical first student messages from `DEEP_COUNSELING_DANISH.md` were run in a fresh synthetic workspace per case using the real Counselor turn path and configured provider. No Analyst or memory extraction was run, because those are later PRs. Thus profile and notebook stayed empty except the synthetic identity; shared conversation history accumulated. No live research was dispatched. Context was in the system prompt. The third model was verified available on the configured OpenAI provider. This is an eight-turn comparison, not a model selection.

`total_ms` covers context construction, the model call, polish, and posting the reply. p95 uses nearest rank (rank 8 of 8). `Asks` counts distinct requests made to the student in the spoken reply after manual review; it does not count action JSON. `Advice/plan` means a proposed education or career route before mirror. `Unsourced world fact` means an outside-world claim absent from research. Each was reviewed turn by turn.

| Case | Model / effort | Words per reply (T1–T8) | Asks per reply (T1–T8) | Advice/plan before mirror | Unsourced world fact | p50 total_ms | p95 total_ms |
| --- | --- | --- | --- | --- | --- | ---: | ---: |
| configured-low | gpt-5-mini / low | 32, 8, 13, 10, 12, 13, 20, 9 | 1, 0, 0, 0, 0, 1, 1, 0 | No on T1–T8 | No on T1–T8 | 2481 | 3774 |
| configured-medium | gpt-5-mini / medium | 26, 19, 9, 21, 22, 24, 29, 24 | 1, 1, 0, 1, 1, 1, 1, 1 | No on T1–T8 | No on T1–T8 | 4158 | 5452 |
| strongest-low | gpt-6-astra / low | 34, 18, 21, 22, 20, 20, 18, 22 | 1, 1, 1, 1, 1, 1, 1, 1 | No on T1–T8 | No on T1–T8 | 4364 | 7792 |

## Quality observations

- Configured model at low effort put the actual question in the JSON `action.question` field while `type` was `none` on turns 2–5 and 8. Those questions are not spoken, so five replies have zero asks. Turn 6 used the generic configured fallback. This is a substantive conversation failure.
- Configured model at medium effort omitted a spoken question on turn 3, repeatedly opened with the same acknowledgment, and inferred on turn 7 that a project was half complete even though the student only said half of a course was watched. That is a student-grounding error, though not an unsourced world fact.
- Strongest-model case asked one spoken question on each turn. Turn 1 requested research even though the prompt called for returning to the goal later; the research action was recorded in the transcript but not dispatched during this isolated comparison.
- The brief exchange cannot establish mirror quality, persistence, or long-journey behavior. No model is selected by this report.

## Full transcript: configured-low (gpt-5-mini, low)

| Turn | Student | Spoken reply | Words | Distinct asks | Advice/plan | Unsourced world fact | total_ms |
| ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| 1 | AoA. mujhe AI engineer banna hai aur Canada jana hai. kaise jaun? | AoA — tum AI engineer ban'na chahte ho aur Canada jaana chahte ho; is goal par baad mein wapas aayenge. Ab batao, abhi tum kya kar rahe ho—padhai, naukri, ya kuch aur? | 32 | 1 | No | No | 3774 |
| 2 | ICS kiya hai is saal, result aa gaya. Ab free hoon | Tumne ICS complete kiya aur ab free ho. | 8 | 0 | No | No | 2745 |
| 3 | 68% aaye. Theek hai bas, maths mein kam aaye | Tumne ICS 68% ke saath pass kiya aur maths mein kam score aaya. | 13 | 0 | No | No | 2354 |
| 4 | dono thora. Calculus bilkul samajh nahi aata tha. Computer mein acha tha | Calculus bilkul samajh nahi aaya aur computer mein acha tha. | 10 | 0 | No | No | 2763 |
| 5 | programming. C++ mein patterns wagaira banana. Python bhi seekha hai maine khud | Tum C++ mein patterns banate thay aur khud se Python seekhi hai. | 12 | 0 | No | No | 2400 |
| 6 | YouTube pe ek 12 ghante ka course hai, us se | I want to understand you properly. Could you tell me a little more? | 13 | 1 | No | No | 2562 |
| 7 | ... aadha shayad. 5-6 ghante | Tumne woh course 5–6 ghante dekh liye; aadha raha. Kya tumne koi chhota programming project banaya jo dekhane layak ho? | 20 | 1 | No | No | 2114 |
| 8 | exams aa gaye the. Phir dobara start nahi kiya | Exams ki wajah se course dobara shuru nahi kiya. | 9 | 0 | No | No | 1844 |

Action payloads and section token counts for each turn are preserved in [the machine-readable result](./pr15-model-matrix.json).

## Full transcript: configured-medium (gpt-5-mini, medium)

| Turn | Student | Spoken reply | Words | Distinct asks | Advice/plan | Unsourced world fact | total_ms |
| ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| 1 | AoA. mujhe AI engineer banna hai aur Canada jana hai. kaise jaun? | Samjha — aap AI engineer banna chahtay hain aur Canada jana chahtay hain; is par baad mein wapas aata hoon. Abhi aap kya kar rahay hain? | 26 | 1 | No | No | 5452 |
| 2 | ICS kiya hai is saal, result aa gaya. Ab free hoon | Samjha — aapne ICS complete kar liya aur ab free hain. Aapke final marks (percent ya grades) kya rahe? | 19 | 1 | No | No | 4057 |
| 3 | 68% aaye. Theek hai bas, maths mein kam aaye | Samjha — aapko 68% miley aur maths kam raha. | 9 | 0 | No | No | 3836 |
| 4 | dono thora. Calculus bilkul samajh nahi aata tha. Computer mein acha tha | Samjha — calculus bilkul samajh nahi aata tha magar computer mein aap acha thay. Computer mein aap ne specifically kya kiya? | 21 | 1 | No | No | 3877 |
| 5 | programming. C++ mein patterns wagaira banana. Python bhi seekha hai maine khud | Samjha — aap C++ mein patterns banate thay aur self-taught Python seekhi. Kya aapne koi project banaya hai jo dikha sakte ho? | 22 | 1 | No | No | 4259 |
| 6 | YouTube pe ek 12 ghante ka course hai, us se | Samjha — aapne YouTube ka 12 ghante ka course kiya. Kya us course se koi project complete kiya hai jo aap dikha sakte ho? | 24 | 1 | No | No | 3397 |
| 7 | ... aadha shayad. 5-6 ghante | Samjha — aapne course ka lagbhag aadha hissa (5-6 ghante) kiya aur project aadha complete hai. Kya aapne project ka code kahin save kiya hai jise main dekh sakun? | 29 | 1 | No | No | 5255 |
| 8 | exams aa gaye the. Phir dobara start nahi kiya | Samjha — aapne project aadha chhor diya kyunki exams aa gaye thay. Aaj rozana kitna waqt AI ya programming seekhne ko de sakte ho? | 24 | 1 | No | No | 4272 |

Action payloads and section token counts for each turn are preserved in [the machine-readable result](./pr15-model-matrix.json).

## Full transcript: strongest-low (gpt-6-astra, low)

| Turn | Student | Spoken reply | Words | Distinct asks | Advice/plan | Unsourced world fact | total_ms |
| ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| 1 | AoA. mujhe AI engineer banna hai aur Canada jana hai. kaise jaun? | Wa alaikum assalam, Danish. AI engineer banne aur Canada jane par wapas aayenge; raaste ki maloomat official sources se check hogi. Pehle tumhein samajhna zaroori hai: aaj kal tumhara aam din kaise guzarta hai? | 34 | 1 | No | No | 7792 |
| 2 | ICS kiya hai is saal, result aa gaya. Ab free hoon | Is saal ICS kiya hai, aur ab free ho. In dinon apna waqt kis kaam mein guzarte ho? | 18 | 1 | No | No | 3707 |
| 3 | 68% aaye. Theek hai bas, maths mein kam aaye | 68% aaye, aur maths mein kam rahe. Maths ki tayari karte waqt sab se zyada mushkil kis cheez mein hoti thi? | 21 | 1 | No | No | 3563 |
| 4 | dono thora. Calculus bilkul samajh nahi aata tha. Computer mein acha tha | Calculus samajh nahi aata tha, lekin computer mein acha tha. Computer mein apne kiye hue kisi ek kaam ke baare mein bataoge? | 22 | 1 | No | No | 3591 |
| 5 | programming. C++ mein patterns wagaira banana. Python bhi seekha hai maine khud | C++ mein patterns banaye aur Python khud seekha. Python mein apne banaye hue kisi ek program ke baare mein bataoge? | 20 | 1 | No | No | 4278 |
| 6 | YouTube pe ek 12 ghante ka course hai, us se | Python YouTube ke 12 ghante wale course se seekha. Us mein se ab tak kya khud code karke chalaya hai? | 20 | 1 | No | No | 4814 |
| 7 | ... aadha shayad. 5-6 ghante | Ab tak course ke takreeban 5–6 ghante dekhe hain. Dekhte hue khud kya code likh kar chalaya tha? | 18 | 1 | No | No | 4450 |
| 8 | exams aa gaye the. Phir dobara start nahi kiya | Exams ki wajah se course ruk gaya, phir dobara shuru nahi hua. Exams ke baad kis cheez mein tumhara waqt guzarta raha? | 22 | 1 | No | No | 4689 |

Action payloads and section token counts for each turn are preserved in [the machine-readable result](./pr15-model-matrix.json).
