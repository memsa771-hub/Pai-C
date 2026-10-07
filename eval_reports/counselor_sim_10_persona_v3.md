# Counselor v2 simulated student evaluation

Runs: 10

| Persona | Mode | Turns | Queued | Repeated slots | Reply rule failures | Leakage | Judge pass | Error |
|---|---|---:|---:|---:|---:|---:|---:|---|
| hamza | chat | 6 | 1 | 1 | 0 | 0 | 6/6 |  |
| ali | chat | 3 | 1 | 0 | 0 | 0 | 6/6 |  |
| ayesha | chat | 7 | 1 | 0 | 0 | 0 | 6/6 |  |
| bilal | chat | 5 | 1 | 0 | 0 | 0 | 6/6 |  |
| sana | chat | 9 | 1 | 0 | 0 | 0 | 6/6 |  |
| usman | chat | 10 | 1 | 2 | 0 | 0 | 6/6 |  |
| volunteer | chat | 3 | 1 | 0 | 0 | 0 | 6/6 |  |
| contradiction | chat | 6 | 1 | 0 | 0 | 0 | 6/6 |  |
| refusal | chat | 8 | 1 | 0 | 0 | 0 | 6/6 |  |
| urdu | chat | 4 | 1 | 0 | 0 | 0 | 6/6 |  |

## Pass rate by persona

| Persona | Queue | No repeat | Reply rules | No leak | Rubric |
|---|---:|---:|---:|---:|---:|
| hamza | 1/1 | 0/1 | 1/1 | 1/1 | 1/1 |
| ali | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| ayesha | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| bilal | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| sana | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| usman | 1/1 | 0/1 | 1/1 | 1/1 | 1/1 |
| volunteer | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| contradiction | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| refusal | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| urdu | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |

## Failing transcripts by check

### repeated_slot

#### hamza / chat / run 0

- student: i missed MBBS merit and honestly don't know what to do
- pai [greet/recent_qualification]: Hi, I'm PAI. What are you studying now, or what did you finish most recently?
- student: i completed fsc pre-medical with 891/1100. feeling pretty down about missing mbbs.
- pai [acknowledge_then_ask/stated_goal]: You completed FSc pre-medical with 891/1100 and you feel pretty down about missing MBBS. What would you like to do next?
- student: yes that's right. i liked biology and lab work, didn't enjoy chemistry. don't want to move away from lahore or islamabad and can afford 3-4 lakh/yr. feeling stuck and low about next steps.
- pai [acknowledge_then_ask/stated_goal]: You completed FSc pre-medical with 891/1100, liked biology and lab work, don’t want to move from Lahore or Islamabad, can afford 3-4 lakh/yr, and feel down about missing MBBS. What would you like to do next?
- student: i want something related to biology and labs, maybe medical lab technology or microbiology. want to stay in lahore or islamabad and affordable. feeling stuck but open to options.
- pai [acknowledge_then_ask/timing]: I hear you. When would you like to start?
- student: as soon as possible. i don't want to waste a year. i'm ready to apply this cycle and start next semester.
- pai [summarize_for_confirmation/None]: You want a biology/lab degree (like medical lab technology or microbiology) because you liked biology and lab work and feel down about missing MBBS; you want to start as soon as possible (apply this cycle, begin next semester), stay in Lahore or Islamabad, and your budget is can afford 3-4 lakh/yr. Field interest listed as medical lab technology or microbiology is pending confirmation. Is this correct or any change?
- student: yes that's correct. i want medical lab technology or microbiology, start asap, stay in lahore or islamabad, budget 3-4 lakh/yr.
- pai [confirm_and_queue_research/None]: I’ll look into routes that fit your goal, including other ways to reach it.

#### usman / chat / run 0

- student: main A Levels year 2 mein hun, aage ka samajh nahi aa raha
- pai [answer_then_ask/qualification_group]: Aap ne kaunsa group ya subjects parhe?
- student: Main sciences parhta hun — Physics, Chemistry, Maths. Faisalabad se hun, 17 saal. AS mein Physics B, Chemistry C, Maths A aaye.
- pai [acknowledge_then_ask/academic_result]: The AS ke marks aap ne bata diye—Physics B, Chemistry C, Maths A—samjha. Aap ke marks, grades ya CGPA kya thay?
- student: Aap ne sahi samjha — AS grades waqai Physics B, Chemistry C, Maths A thay. CGPA nahin hai, sirf ye grades hain. Aage kya kariye yeh samajh nahi aa raha.
- pai [answer_then_ask/stated_goal]: Aap aage kya karna chahte hain?
- student: Mujhe pata nahi — parents engineering chahte hain lekin mujhe graphic design aur app UI zyada pasand hain. Ek saal se Figma projects kiye hain. Father shayad software ko maan jaye. Budget bhi limited hai.
- pai [acknowledge_then_ask/stated_goal]: Main samajh raha hoon. Aap aage kya karna chahte hain?
- student: Aap ne sahi samjha — parents engineering chahte hain magar mujhe graphic design aur app UI zyada pasand hain. Ek saal se Figma projects kiye hain, aur father shayad software ko maan jaye. Budget 5-6 lakh/saal hai.
- pai [acknowledge_then_ask/stated_goal]: Samjha — parents engineering/software chahte hain, aapko graphic design aur app UI zyada pasand hain, ek saal se Figma projects kar rahe ho, aur Budget 5-6 lakh/saal hai. Aap aage kya karna chahte hain?
- student: Haan, sahi samjha. Main abhi confused hun — engineering ke liye jaana chahte hain parents lekin mera interest graphic design/app UI mein zyada hai. Main chahunga ke aap madad karein decide karne mein.
- pai [returning_student/goal_reason]: Is raaste mein aap ki dilchaspi kyun hai?
- student: Mujhe design karna pasand hai kyunki creative hoon aur problems ko visual tareeqay se solve karna achha lagta hai. Apps ka interface simple aur attractive banana mujhe satisfy karta hai, aur Figma projects karte hue mujhe time achay lagay. Engineering sirf parents ki expectation lagti hai, mujhe uss mein dilchaspi utni nahi jitni design mein hai.
- pai [acknowledge_then_ask/envisioned_outcome]: Samajh gaya — aap design (graphic/app UI) pasand karte hain kyunki creative ho, problems ko visual solve karna acha lagta hai, aur Figma par kaam karke acha time guzarta hai; parents engineering chahte hain. Us ke baad aap khud ko kya karte dekhte hain?
- student: Main khud ko 2-3 saal mein ek junior UI/UX designer ke role mein dekhna chahta hun, freelance projects aur chhote apps ke liye interfaces banata hua. 5 saal mein main ek acha portfolio aur kuch regular clients chahunga, shayad kisi software company mein product design pe kaam. Agar parents chahein to engineering degree ke sath part-time design ya bootcamp bhi kar sakta hun, lekin primary focus design hi hoga.
- pai [summarize_for_confirmation/None]: Kya main ne aap ka maqsad sahi samjha hai?
- student: Haan, bilkul sahi samjha aap ne.
- pai [summarize_for_confirmation/None]: Aap design (graphic / app UI) mein genuinely interested hain kyunki creative ho aur problems ko visual tareeqay se solve karna pasand hai; aap 2–3 saal mein junior UI/UX designer banna, freelance projects lena aur 5 saal mein acha portfolio + regular clients chahte ho, lekin parents engineering prefer karte hain. Field interest: graphic design / app UI; budget: Budget 5-6 lakh/saal; timing: 2-3 saal; location limit: Faisalabad; family preference for engineering was noted. Kya yeh sahi hai ya koi correction?
- student: Haan, bilkul sahi hai. Bas itna add karunga ke mera father software mein chal sakta hai agar main design + software ka raasta dikhaun.
- pai [confirm_and_queue_research/None]: Main aap ke goal ke liye munasib raaste dekhunga, aur alternatives bhi.


## Sample transcripts

### hamza / chat / run 0

- student: i missed MBBS merit and honestly don't know what to do
- pai [greet/recent_qualification]: Hi, I'm PAI. What are you studying now, or what did you finish most recently?
- student: i completed fsc pre-medical with 891/1100. feeling pretty down about missing mbbs.
- pai [acknowledge_then_ask/stated_goal]: You completed FSc pre-medical with 891/1100 and you feel pretty down about missing MBBS. What would you like to do next?
- student: yes that's right. i liked biology and lab work, didn't enjoy chemistry. don't want to move away from lahore or islamabad and can afford 3-4 lakh/yr. feeling stuck and low about next steps.
- pai [acknowledge_then_ask/stated_goal]: You completed FSc pre-medical with 891/1100, liked biology and lab work, don’t want to move from Lahore or Islamabad, can afford 3-4 lakh/yr, and feel down about missing MBBS. What would you like to do next?
- student: i want something related to biology and labs, maybe medical lab technology or microbiology. want to stay in lahore or islamabad and affordable. feeling stuck but open to options.
- pai [acknowledge_then_ask/timing]: I hear you. When would you like to start?
- student: as soon as possible. i don't want to waste a year. i'm ready to apply this cycle and start next semester.
- pai [summarize_for_confirmation/None]: You want a biology/lab degree (like medical lab technology or microbiology) because you liked biology and lab work and feel down about missing MBBS; you want to start as soon as possible (apply this cycle, begin next semester), stay in Lahore or Islamabad, and your budget is can afford 3-4 lakh/yr. Field interest listed as medical lab technology or microbiology is pending confirmation. Is this correct or any change?
- student: yes that's correct. i want medical lab technology or microbiology, start asap, stay in lahore or islamabad, budget 3-4 lakh/yr.
- pai [confirm_and_queue_research/None]: I’ll look into routes that fit your goal, including other ways to reach it.

### ali / chat / run 0

- student: hey
- pai [redirect_then_ask/recent_qualification]: I can help with your study or career plans. What are you studying now, or what did you finish most recently?
- student: I finished FSc Pre-Engineering with 844/1100. I'm in Islamabad and aiming for a bachelor's in the USA—ideally in data science or a tech field, maybe at a good university that leads to jobs abroad. My budget is about PKR 15 lakh per year including living. I haven't taken any English test yet. Start would be next year.
- pai [summarize_for_confirmation/None]: You want to start a bachelor’s in the USA next year, ideally in data science or a tech field so you can attend a good university that leads to jobs abroad; you finished FSc Pre‑Engineering with 844/1100 and are currently in Islamabad. Your budget is about PKR 15 lakh per year including living, and you haven’t taken an English test yet. Is that correct or anything to change?
- student: Yes, that’s correct.
- pai [confirm_and_queue_research/None]: I’ll look into routes that fit your goal, including other ways to reach it.

### ayesha / chat / run 0

- student: I'm in BS CS semester 6 and looking at what comes next
- pai [greet/recent_qualification]: Hi, I'm PAI. What are you studying now, or what did you finish most recently?
- student: I'm in BS CS, currently in semester 6. My CGPA is 3.21. I'm considering applying for a funded master's abroad, taking a job here in Pakistan, or doing a local MS. Earning matters because my family needs support, so abroad is only an option if fully funded. I like web development and some ML, and I have a two-month React internship experience.
- pai [ask/envisioned_outcome]: What do you picture doing after that?
- student: I picture either getting a job here to start earning and support my family, or if I get a fully funded offer abroad, doing a master's there to specialize. Ideally something in web development or a role involving ML, but income and funding will decide. Marker: 3.21
- pai [ask/budget]: Roughly how much can you spend on this?
- student: I can’t increase the budget — family can’t afford to fund studies abroad, so I need either a fully funded scholarship/assistantship or a job here that earns enough to help at home.
- pai [acknowledge_then_ask/timing]: Got it — you need either a fully funded study option abroad or a job here that starts earning for your family. When would you like to start?
- student: I’d like to start after I finish semester 8 — so in about a year and a half. If I can get a funded MS abroad I’d start then, otherwise I’d look for a job here as soon as I graduate. Yes, you summarized correctly.
- pai [ask/location_limits]: Are there places you need to stay in or avoid?
- student: I don’t have specific location limits — I’m open to cities in Pakistan where tech jobs are available. For abroad, I’d only go if it’s fully funded, so location depends on where I get funding. Otherwise I’d prefer places with good job markets and reasonable living costs.
- pai [summarize_for_confirmation/None]: You want either a fully funded master's abroad or a job in Pakistan after your BS CS so you can start earning to support your family, with preference for web development or ML roles; funding/income will decide which path you take. Timing: you plan to start in about a year and a half after finishing semester 8; budget was declined (you need fully funded abroad or a job here); location limits: Pakistani tech cities or abroad only if fully funded. Is that correct or do you want any change?
- student: Yes, that summary is correct.
- pai [confirm_and_queue_research/None]: I’ll look into routes that fit your goal, including other ways to reach it.
