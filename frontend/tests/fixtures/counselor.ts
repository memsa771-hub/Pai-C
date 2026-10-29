import type {
  LivingPicture,
  PathResult,
  Programs,
} from "@/lib/counselor-workspace";
import type { Possibility } from "@/lib/possibilities";
import type { VaultCatalog, VaultEntry, VaultView } from "@/lib/vault";
import type { ChosenRoute, FieldCard, RoadmapPage, RouteStep, RouteTime, Verdict } from "@/lib/roadmap";
import type { MirrorCard } from "@/lib/mirror";
export const possibilities: Possibility[] = [
  {
    id: "path-one",
    title: "Practical design",
    why: "You enjoy making useful things and understanding how parts work together.",
    status: "suggested",
    evidence: [
      { text: "I fixed a broken lamp with my friend.", item_id: "e1" },
    ],
    source: "analyzer",
    fit: [
      { label: "Hands-on making", status: "have", note: "You already repair and build things.",
        evidence: ["I fixed a broken lamp with my friend."] },
      { label: "Drawing ideas on paper", status: "partial", note: "", evidence: ["I sketch before I build."] },
      { label: "Paying for a full degree", status: "unknown", note: "", evidence: [] },
    ],
    unknowns: [],
  },
  {
    id: "path-two",
    title: "Applied computing",
    why: "You described enjoying the process of testing and improving a small project.",
    status: "saved",
    evidence: [{ text: "I kept changing it until it worked.", item_id: "e2" }],
    unknowns: [],
  },
];
export const picture: LivingPicture = {
  coverage: Object.fromEntries(
    [
      "status",
      "history",
      "interests",
      "strengths",
      "family_social",
      "values",
      "pressures",
      "sure",
      "goals",
      "options",
    ].map((key, i) => [key, {
      covered: i < 7,
      item_count: [2, 3, 2, 2, 2, 1, 1, 0, 0, 0][i],
      evidence: (["confirmed", "shown", "stated", "shown", "stated", "stated", "stated", null, null, null] as const)[i],
    }]),
  ),
  sections: {
    interests: [
      { id: "in1", value: "Taking things apart to see how they work", evidence: "I like opening old radios to see what is inside.", kind: "said" },
      { id: "in2", value: "Sketching product ideas", evidence: "I keep a notebook of drawings for gadgets.", kind: "shown" },
      { id: "in3", value: "Helping friends fix their phones", evidence: "Friends bring me their phones when something breaks.", kind: "said" },
    ],
    values: [{ id: "v1", value: "Work that is useful to people", evidence: "I want to make things people actually use.", kind: "said" }],
    goals: [{ id: "g1", value: "Explore design", evidence: "I want to see what design involves.", kind: "said", category: "self" }],
    options: [],
  },
  personal: {
    world: {
      people: [
        {
          role: "Parent",
          wish: "A stable career",
          concern: "Financial security",
          evidence: "My parent worries about steady work.",
        },
        {
          role: "Older sibling",
          wish: "That I choose something I enjoy",
          concern: "That I might pick a course only because friends did",
          evidence: "My sibling says I should follow what I like.",
        },
      ],
    },
    self: [
      {
        id: "i1",
        value: "Making things work",
        evidence: "I fixed a broken lamp.",
      },
    ],
    source: [
      {
        id: "g1",
        value: "Explore design",
        evidence: "I want to see what design involves.",
      },
    ],
    pressures: {
      items: [
        {
          value: "Study close to home",
          evidence: "I help at home most evenings.",
        },
      ],
    },
    sure: { score: 6, history: [] },
  },
  capabilities: {
    emerging: [
      {
        id: "s1",
        value: "Practical troubleshooting",
        capability_status: "emerging",
        evidence: "I tried two different repairs.",
      },
    ],
  },
  academic: { records: {} },
  picture: {
    header: { name: "Sam Taylor", education_line: { level: "fsc", level_label: "FSc",
      groups: [{ code: "pre_engineering", label: "Pre-Engineering" }], percent: 78, text: "FSc Pre-Engineering, 78%" } },
    unknowns: [
      { area: "pressures", label: "Pressures & limits", question_key: "topic_text.pressures", priority: 4 },
      { area: "sure", label: "Certainty", question_key: "topic_text.sure", priority: 8 },
    ],
    text: { sentences: ["You are in FSc Pre-Engineering with 78%.", "You like finding out how machines work.",
      "Your family hopes for medicine; you lean to engineering."], version: "v1", written_at: "2026-10-27T09:00:00+00:00" },
    ready: true,
    version: "v1",
  },
  moments: { explore_area: "m1", first_picture: "m2", mirror: "m3" },
  ratings: [{ version: 1, understood: 5, before: 3, after: 6 }],
};
/** One Vault entry as /v1/vault shapes it; only what a case needs is overridden. */
export const entry = (over: Partial<VaultEntry> & Pick<VaultEntry, "type" | "id" | "value" | "display" | "label">): VaultEntry => ({
  kind: "fact", level: "stated", badge: "Stated", source: "user_explicit", document: null,
  observed_at: "2026-10-16T09:00:00+00:00", confirmed_at: null, fresh_until: null, stale: false,
  in_question: false, disagreements: [], ...over,
});
const resultCard = { file_id: "result-card", page: 1, filename: "Result card.jpg" };
export const vault: VaultView = {
  details: {
    about: { label: "About you", entries: [
      entry({ type: "identity.full_name", id: "name", value: "Sam Taylor", display: "Sam Taylor", label: "Full name",
        level: "confirmed", badge: "Confirmed", confirmed_at: "2026-10-18T09:00:00+00:00" }),
      entry({ type: "location.current_city", id: "city", value: "My city", display: "My city", label: "Current city",
        stale: true, fresh_until: "2026-10-20T09:00:00+00:00" }),
      entry({ type: "identity.date_of_birth", id: "dob", value: "2008-03-12", display: "2008-03-12", label: "Date of birth",
        level: "inferred", badge: "PAI's guess" }),
      entry({ type: "location.current_country", id: "country", value: "Pakistan", display: "Pakistan", label: "Current country",
        in_question: true, badge: "In question" }),
    ] },
    education: { label: "Education", entries: [
      entry({ kind: "record", type: "education", id: "education-earlier", label: "Education", level: "shown", badge: "From document",
        value: { qualification_name: "matric", institution_name: "Community school", percentage: 81, academic_status: "completed", end_date: "2024-05-30" },
        display: "Matric, Community school, 81, completed, 2024-05-30", document: resultCard,
        disagreements: [{ value: { percentage: 79 }, display: "79", source: "document", document: { file_id: "old-card", page: null, filename: "Old card.pdf" } }] }),
      entry({ kind: "record", type: "education", id: "education", label: "Education", level: "shown", badge: "From document",
        value: { qualification_name: "Secondary education", institution_name: "Community school", academic_status: "current" },
        display: "Secondary education, Community school, current", document: { file_id: "document", page: null, filename: "Student record.pdf" } }),
    ] },
    tests: { label: "Tests", entries: [
      entry({ kind: "record", type: "test_attempt", id: "test-one", label: "Test",
        value: { test_type: "Practice aptitude test", overall_score: "64", test_date: "2026-09-20" },
        display: "Practice aptitude test, 64, 2026-09-20" }),
    ] },
    money_and_place: { label: "Money and place", entries: [] },
    documents: { label: "Documents", entries: [] },
  },
  story: [
    { type: "interest", label: "Interest", rich: false, next_step: null, entries: [
      entry({ kind: "item", type: "interest", id: "fixing", value: { text: "Fixing things" }, display: "Fixing things", label: "Interest" }),
    ] },
    { type: "family_member", label: "Family member", rich: false, next_step: null, entries: [
      entry({ kind: "item", type: "family_member", id: "parent", value: { relation: "mother", wish: "Financial security" },
        display: "Mother, Financial security", label: "Family member" }),
    ] },
    { type: "pressure", label: "Pressure", rich: false, next_step: "What weighs on your choice?", entries: [] },
    { type: "option", label: "Option", rich: false, next_step: null, entries: [] },
    { type: "myth", label: "Myth", rich: false, next_step: null, entries: [] },
  ],
  // Conflict-heavy on purpose: the offline preview (?view=profile) shows the
  // banner, the summary and every kind of card the review dialog walks.
  conflicts: [
    { id: "c-city", kind: "fact", type: "location.current_city", entry_id: "city",
      summary: "Two different answers for your current city.", question: "Which current city is right?",
      current: "Islamabad", proposed: "Lahore", current_display: "Islamabad", proposed_display: "Lahore",
      answers: ["keep_current", "accept_proposed", "both_true", "provide_new"],
      current_source: { level: "stated", badge: "Stated", said_on: "2026-10-12T09:00:00+00:00", document: null },
      proposed_source: { level: "shown", badge: "From document", said_on: "2026-10-18T09:00:00+00:00", document: resultCard },
      created_at: "2026-10-18T09:00:00+00:00" },
    { id: "c-owner", kind: "document_owner", type: null, entry_id: null,
      summary: "A document may belong to someone else.", question: "Is Result card.jpg your document?",
      current: ["Sam Taylor"], proposed: ["Alex Doe"], current_display: "Sam Taylor", proposed_display: "Alex Doe",
      answers: ["keep_current", "accept_proposed"], current_source: null,
      proposed_source: { level: "shown", badge: "From document", said_on: "2026-10-18T09:00:00+00:00", document: resultCard },
      created_at: "2026-10-18T09:01:00+00:00" },
    { id: "c-country", kind: "fact", type: "location.current_country", entry_id: "country",
      summary: "Two different answers for your current country.", question: "Which current country is right?",
      current: "Pakistan", proposed: "Qatar", current_display: "Pakistan", proposed_display: "Qatar",
      answers: ["keep_current", "accept_proposed", "both_true", "provide_new"],
      current_source: { level: "confirmed", badge: "Confirmed", said_on: "2026-10-10T09:00:00+00:00", document: null },
      proposed_source: { level: "inferred", badge: "PAI's guess", said_on: "2026-10-19T09:00:00+00:00", document: null },
      created_at: "2026-10-19T09:00:00+00:00" },
  ],
  stale: [],
};
export const vaultCatalog: VaultCatalog = { types: [
  { key: "identity.full_name", label: "Full name", storage: "fact", shown_on: "details", section: "about",
    inputs: ["chat", "details"], schema: { type: "string" }, choices: {} },
  { key: "location.current_city", label: "Current city", storage: "fact", shown_on: "details", section: "about",
    inputs: ["chat", "details"], schema: { type: "string" }, choices: {} },
  { key: "education", label: "Education", storage: "record", shown_on: "details", section: "education", inputs: ["chat", "document", "details"],
    schema: { type: "object", required: ["qualification_name"], properties: {
      qualification_name: { type: "string" }, institution_name: { type: "string" }, academic_status: { type: "string" }, details: { type: "object" } } },
    choices: { qualification_name: [{ code: "matric", label: "Matric" }, { code: "fsc", label: "FSc" }] } },
  { key: "interest", label: "Interest", storage: "item", shown_on: "story", section: null, inputs: ["chat", "story"],
    schema: { type: "object", required: ["text"], properties: { text: { type: "string" }, example: { type: "string" } } }, choices: {} },
  { key: "family_member", label: "Family member", storage: "item", shown_on: "story", section: null, inputs: ["chat", "story"],
    schema: { type: "object", required: ["relation"], properties: { relation: { type: "string" }, wish: { type: "string" }, lives_with: { type: "boolean" } } },
    choices: { relation: [{ code: "father", label: "Father" }, { code: "mother", label: "Mother" }] } },
  { key: "pressure", label: "Pressure", storage: "item", shown_on: "story", section: null, inputs: ["chat", "story"],
    schema: { type: "object", required: ["text"], properties: { text: { type: "string" }, kind: { type: "string", enum: ["money", "time"] } } }, choices: {} },
  { key: "option", label: "Option", storage: "item", shown_on: "story", section: null, inputs: ["chat", "story"],
    schema: { type: "object", required: ["text"], properties: { text: { type: "string" } } }, choices: {} },
  { key: "myth", label: "Myth", storage: "item", shown_on: "story", section: null, inputs: ["chat", "story"],
    schema: { type: "object", required: ["text"], properties: { text: { type: "string" }, about: { type: "string" } } }, choices: {} },
] };
export const pathResult: PathResult = {
  possibility: possibilities[0],
  status: "completed",
  path: {
    what_it_is: "Design turns an idea into something people can use.",
    what_you_study: ["Drawing ideas", "Materials", "Testing prototypes"],
    work_day: "A day might include sketching, making and testing.",
    skills: ["Observation", "Iteration", "Practical problem solving"],
    fit_for: [
      {
        observation: "Practical work seems worth exploring.",
        evidence: "I fixed a broken lamp with my friend.",
      },
    ],
    fit_against: [],
    ways_in: ["Read a course outline", "Try a small project"],
    try_it:
      "Sketch an improvement to an everyday object, then try a paper prototype.",
  },
  facts: [],
  missing: ["verified_career_sources"],
};
export const programs: Programs = {
  status: "completed",
  programs: [],
  missing: ["verified_program_sources"],
};

// The Roadmap page for an FSc Pre-Engineering student with 78%: the shape of
// backend RoadmapEngine.build (app/pai_c/roadmap/engine.py).
const verdict = (v: Partial<Verdict>): Verdict => ({
  status: "open", reasons: [], needs: [], tests: [], years: null, min_percent: null, student_percent: 78,
  confidence: "official", sources: [], subjects: [], ...v,
});
const result = { id: "education:fsc", level: "shown" as const, source_label: "Result card.jpg" };
const PEC = { source: "https://www.pec.org.pk/regulations.pdf", confidence: "official" as const };
const step = (key: string, label_key: string, values: Record<string, unknown>, status: RouteStep["status"],
  over: Partial<RouteStep> = {}): RouteStep => ({ key, kind: key.split(":")[0], label_key, values, status,
  colour: ({ done: "green", half: "yellow", not: "red" } as const)[status], evidence: null, rule: null, manual_done: false, ...over });
const finish = step("complete_intermediate", "step_finish_exam", { level: "FSc", month: "May", year: 2027 }, "half", { evidence: result });
const group = step("group", "step_group", { groups: [{ code: "pre_engineering", label: "Pre-Engineering", route_label: "FSc Pre-Engineering" }] },
  "done", { evidence: result, rule: PEC });
const basis = (step: string | null, event_key: string, month: number | null, year: number | null, confidence = "official") =>
  ({ step, event_key, month, year, source: month ? "https://ecat.uet.edu.pk/" : null, confidence });
export const eeSteps: RouteStep[] = [
  group, finish,
  step("marks", "step_marks", { min: 60, have: 78 }, "done", { evidence: result, rule: PEC }),
  step("test:ECAT / NET", "step_test_pass", { name: "ECAT / NET", pass: 33 }, "not",
    { kind: "test", rule: { source: "https://ecat.uet.edu.pk/", confidence: "official" } }),
  step("apply", "step_apply", { degree: "Electrical Engineering" }, "not"),
  step("degree", "step_degree", { degree: "Electrical Engineering", years: 4 }, "not", { rule: PEC }),
];
export const eeTime: RouteTime = {
  to_entry_months: 11, to_finish_years: 4.9, degree_years: 4, confidence: "secondary",
  next_intake: { label: "September intake", start_month: 9, year: 2027 },
  basis: [basis("complete_intermediate", "hssc_part2_exam", 5, 2027, "secondary"), basis("complete_intermediate", "hssc_part2_result", 9, 2027, "secondary"),
    basis("test:ECAT / NET", "ecat", 6, 2027), basis("test:ECAT / NET", "ecat:result", 6, 2027), basis(null, "nust_ug", 9, 2027)],
};
const pharmSteps: RouteStep[] = [
  { ...group, rule: { source: "https://example.org/pharm", confidence: "uncertain" } }, finish,
  step("marks", "step_marks", { min: 60, have: 78 }, "done", { evidence: result }),
  step("bridge", "step_bridge", { text: "Biology bridge course at some universities" }, "not",
    { rule: { source: "https://example.org/pharm", confidence: "uncertain" } }),
  step("test:University test", "step_test", { name: "University test" }, "not", { kind: "test" }),
  step("apply", "step_apply", { degree: "Pharmacy" }, "not"),
  step("degree", "step_degree", { degree: "Pharmacy", years: 5 }, "not"),
];
const pharmTime: RouteTime = {
  to_entry_months: null, to_finish_years: null, degree_years: 5, confidence: "uncertain", next_intake: null,
  basis: [basis("complete_intermediate", "hssc_part2_exam", 5, 2027, "secondary"), basis("test:University test", "", null, null, "uncertain")],
};
export const roadmapCards: FieldCard[] = [
  { possibility_id: "path-ee", field_key: "electrical_engineering", title: "Electrical Engineering", family: "engineering",
    why: "You like finding out how circuits and machines work.", status: "open",
    verdict: verdict({ tests: [{ name: "ECAT / NET", pass_percent: 33 }], years: 4, min_percent: 60,
      sources: ["https://www.pec.org.pk/regulations.pdf"] }), steps: eeSteps, time: eeTime },
  { possibility_id: "path-cs", field_key: "computer_science", title: "Computer Science", family: "computing",
    why: "You kept changing your project until it worked.", status: "open",
    verdict: verdict({ tests: [{ name: "University test", pass_percent: null }], years: 4, min_percent: 50,
      confidence: "secondary", sources: ["https://www.hec.gov.pk/criteria"] }),
    steps: [group, finish, step("marks", "step_marks", { min: 50, have: 78 }, "done", { evidence: result }),
      step("test:University test", "step_test", { name: "University test" }, "not", { kind: "test" }),
      step("apply", "step_apply", { degree: "Computer Science" }, "not"), step("degree", "step_degree", { degree: "Computer Science", years: 4 }, "not")],
    time: { ...eeTime, to_entry_months: 10, to_finish_years: 4.8, confidence: "uncertain" } },
  { possibility_id: "path-pharm", field_key: "pharmacy", title: "Pharmacy", family: "health",
    why: "You are curious about how medicines help people.", status: "step",
    verdict: verdict({ status: "step", reasons: [{ key: "rule_step", text: "Biology bridge course at some universities" }],
      needs: [{ kind: "bridge", detail: { text: "Biology bridge course at some universities", source: "https://example.org/pharm" } }],
      tests: [{ name: "University test", pass_percent: null }], years: 5, min_percent: 60, confidence: "uncertain",
      sources: ["https://example.org/pharm"] }), steps: pharmSteps, time: pharmTime },
  { possibility_id: "path-mbbs", field_key: "mbbs", title: "MBBS", family: "health",
    why: "You said you want to help people directly.", status: "not_open",
    verdict: verdict({ status: "not_open", reasons: [{ key: "not_open_group", group_code: "pre_engineering", group_label: "Pre-Engineering" }],
      tests: [{ name: "MDCAT", pass_percent: 55 }], years: 5, min_percent: 60, sources: ["https://pmdc.pk/regulations"] }) },
  { possibility_id: "path-game", field_key: null, title: "Game design", family: null,
    why: "You enjoy making small games.", status: "unknown",
    verdict: verdict({ status: "unknown", reasons: [{ key: "cannot_check" }], confidence: null }) },
];
export const chosenRoute: ChosenRoute = {
  id: "route-one", field_key: "electrical_engineering", possibility_id: "path-ee", title: "Electrical Engineering",
  chosen_at: "2026-10-20T10:00:00Z", steps: eeSteps, time: eeTime,
  snapshot_steps: eeSteps.map(({ key, label_key, values, status }) => ({ key, label_key, values, status })),
  steps_done: [], snapshot_verdict: roadmapCards[0].verdict, live_status: "open",
};
export const roadmapPage: RoadmapPage = {
  education_line: { level: "fsc", level_label: "FSc", groups: [{ code: "pre_engineering", label: "Pre-Engineering" }], percent: 78 },
  counts: { open: 2, step: 1, not_open: 1, unknown: 1 },
  fields: roadmapCards,
  chosen: null,
  rules_as_of: "2026-10",
};

// The Mirror state card (backend app/pai_c/mirror/engine.py): an FSc
// Pre-Engineering student whose family hopes for medicine.
type Entry = MirrorCard["areas"][number]["entries"][number];
const mEntry = (id: string, text: string, evidence: Entry["evidence"], source_label: string): Entry =>
  ({ id, text, evidence, source_label, observed_at: "2026-10-26T09:00:00+00:00" });
const tension = { a_id: "item:parent", b_id: "item:goal", note_key: "tension.family_vs_goal" };
const area = (key: string, label: string, level: 0 | 1 | 2 | 3, entries: Entry[] = [], over = {}): MirrorCard["areas"][number] =>
  ({ key, label, level, entries, bars: [], tension: [], ...over });
export const mirrorCard: MirrorCard = {
  version: "v1",
  header: picture.picture!.header,
  areas: [
    area("history", "Education & experience", 3, [mEntry("education:education", "FSc Pre-Engineering, 78%", "shown", "Result card.jpg"),
      mEntry("education:education-earlier", "Matric Science, 81%", "confirmed", "Details")],
      { bars: [{ label: "Physics", percent: 81 }, { label: "Mathematics", percent: 74 }, { label: "Chemistry", percent: 70 }] }),
    area("goals", "Goals & whose wish", 1, [mEntry("item:goal", "Become an electrical engineer", "stated", "Chat")], { tension: [tension] }),
    area("options", "Options & myths", 1, [mEntry("item:option", "Considering ECAT", "stated", "Chat")]),
    area("pressures", "Pressures & limits", 0),
    area("interests", "Interests", 2, [mEntry("item:fixing", "Fixing things", "stated", "Chat"),
      mEntry("item:radio", "Built a small radio", "shown", "Radio photo.jpg")]),
    area("status", "Current life", 2, [mEntry("fact:identity.current_status", "Current situation: Studying", "confirmed", "Onboarding")]),
    area("family_social", "Family", 1, [mEntry("item:parent", "Mother, wishes MBBS", "stated", "Chat")], { tension: [tension] }),
    area("sure", "Certainty", 0),
    area("values", "Values", 0),
    area("strengths", "Strengths", 1, [mEntry("item:maths", "Good at maths", "inferred", "Chat")]),
  ],
  unknowns: [
    { area: "pressures", label: "Pressures & limits", question_key: "topic_text.pressures", priority: 4 },
    { area: "sure", label: "Certainty", question_key: "topic_text.sure", priority: 8 },
    { area: "values", label: "Values", question_key: "topic_text.values", priority: 9 },
  ],
  text: picture.picture!.text,
  ready: true,
};
/** Onboarding only: two areas known, no text yet, not ready. */
export const mirrorEmpty: MirrorCard = {
  version: "v0",
  header: { name: "Sam Taylor", education_line: { ...picture.picture!.header.education_line!, percent: null, text: "FSc Pre-Engineering" } },
  areas: mirrorCard.areas.map((a) => a.key === "history"
    ? { ...a, level: 1, bars: [], entries: [mEntry("education:education", "FSc Pre-Engineering", "stated", "Onboarding")] }
    : a.key === "status" ? { ...a, level: 1, entries: [mEntry("fact:identity.current_status", "Current situation: Studying", "stated", "Onboarding")] }
    : { ...a, level: 0, entries: [], tension: [] }),
  unknowns: ["goals", "options", "pressures", "interests", "family_social", "sure", "values", "strengths"].map((key, i) => ({
    area: key, label: mirrorCard.areas.find((a) => a.key === key)!.label, question_key: `topic_text.${key}`, priority: i + 2 })),
  text: null,
  ready: false,
};
