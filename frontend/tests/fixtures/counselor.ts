import type {
  LivingPicture,
  PathResult,
  Programs,
} from "@/lib/counselor-workspace";
import type { Possibility } from "@/lib/possibilities";
import type { VaultCatalog, VaultEntry, VaultView } from "@/lib/vault";
import type { ChosenRoute, FieldCard, RoadmapPage, Verdict } from "@/lib/roadmap";
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
    roadmap_id: null,
  },
  {
    id: "path-two",
    title: "Applied computing",
    why: "You described enjoying the process of testing and improving a small project.",
    status: "saved",
    evidence: [{ text: "I kept changing it until it worked.", item_id: "e2" }],
    unknowns: [],
    roadmap_id: null,
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
    you_say: {
      text: "You want a direction that feels like your own.",
      evidence: [],
    },
    life_shows: {
      text: "You keep returning to practical projects.",
      evidence: [],
    },
    pressure: { text: "Family security matters to you.", evidence: [] },
    you_want: {
      text: "You want to test a path before committing.",
      evidence: [],
    },
  },
  mirror_status: "confirmed",
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
export const roadmapCards: FieldCard[] = [
  { possibility_id: "path-ee", field_key: "electrical_engineering", title: "Electrical Engineering", family: "engineering",
    why: "You like finding out how circuits and machines work.", status: "open",
    verdict: verdict({ tests: [{ name: "ECAT / NET", pass_percent: 33 }], years: 4, min_percent: 60,
      sources: ["https://www.pec.org.pk/regulations.pdf"] }) },
  { possibility_id: "path-cs", field_key: "computer_science", title: "Computer Science", family: "computing",
    why: "You kept changing your project until it worked.", status: "open",
    verdict: verdict({ tests: [{ name: "University test", pass_percent: null }], years: 4, min_percent: 50,
      confidence: "secondary", sources: ["https://www.hec.gov.pk/criteria"] }) },
  { possibility_id: "path-pharm", field_key: "pharmacy", title: "Pharmacy", family: "health",
    why: "You are curious about how medicines help people.", status: "step",
    verdict: verdict({ status: "step", reasons: [{ key: "rule_step", text: "Biology bridge course at some universities" }],
      needs: [{ kind: "bridge", detail: { text: "Biology bridge course at some universities", source: "https://example.org/pharm" } }],
      tests: [{ name: "University test", pass_percent: null }], years: 5, min_percent: 60, confidence: "uncertain",
      sources: ["https://example.org/pharm"] }) },
  { possibility_id: "path-mbbs", field_key: "mbbs", title: "MBBS", family: "health",
    why: "You said you want to help people directly.", status: "not_open",
    verdict: verdict({ status: "not_open", reasons: [{ key: "not_open_group", group_code: "pre_engineering", group_label: "Pre-Engineering" }],
      tests: [{ name: "MDCAT", pass_percent: 55 }], years: 5, min_percent: 60, sources: ["https://pmdc.pk/regulations"] }) },
  { possibility_id: "path-game", field_key: null, title: "Game design", family: null,
    why: "You enjoy making small games.", status: "unknown",
    verdict: verdict({ status: "unknown", reasons: [{ key: "cannot_check" }], confidence: null }) },
];
export const chosenRoute: ChosenRoute = {
  id: "route-one", field_key: "pharmacy", possibility_id: "path-pharm", title: "Pharmacy", chosen_at: "2026-10-20T10:00:00Z",
  steps: [{ key: "step_bridge", text: "Biology bridge course at some universities" }, { key: "step_test", name: "University test" },
    { key: "step_apply", degree: "Pharmacy" }],
  steps_done: [true, false, false], snapshot_verdict: roadmapCards[2].verdict, live_status: "step",
};
export const roadmapPage: RoadmapPage = {
  education_line: { level: "fsc", level_label: "FSc", groups: [{ code: "pre_engineering", label: "Pre-Engineering" }], percent: 78 },
  counts: { open: 2, step: 1, not_open: 1, unknown: 1 },
  fields: roadmapCards,
  chosen: null,
};
