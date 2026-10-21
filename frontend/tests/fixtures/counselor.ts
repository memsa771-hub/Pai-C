import type {
  LivingPicture,
  ProfileCard,
  PathResult,
  Programs,
} from "@/lib/counselor-workspace";
import type { Possibility } from "@/lib/possibilities";
export const possibilities: Possibility[] = [
  {
    id: "path-one",
    title: "Practical design",
    why: "You enjoy making useful things and understanding how parts work together.",
    status: "suggested",
    evidence: [
      { text: "I fixed a broken lamp with my friend.", item_id: "e1" },
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
export const cards: ProfileCard[] = [
  {
    kind: "vault_fact",
    key: "identity.full_name",
    id: "name",
    value: "Sam Taylor",
    digest: "a".repeat(64),
    evidence_level: "confirmed",
    source: { quote: "My name is Sam Taylor." },
    updated_at: "2026-10-18",
  },
  {
    kind: "vault_fact",
    key: "location.current_city",
    id: "city",
    value: "My city",
    digest: "c".repeat(64),
    evidence_level: "stated",
    source: { quote: "I live in my city with my family." },
    updated_at: "2026-10-16",
  },
  {
    kind: "vault_fact",
    key: "identity.date_of_birth",
    id: "dob",
    value: "2008-03-12",
    digest: "d".repeat(64),
    evidence_level: "stated",
    source: {},
    updated_at: "2026-10-16",
  },
  {
    kind: "education",
    key: "education",
    id: "education-earlier",
    value: {
      qualification_name: "Lower secondary certificate",
      institution_name: "Community school",
      board: "Regional board",
      percentage: 81,
      academic_status: "completed",
      end_date: "2024-05-30",
    },
    digest: "e".repeat(64),
    evidence_level: "shown",
    source: { quote: "Result card", file_id: "result-card" },
    updated_at: "2026-10-14",
  },
  {
    kind: "test_attempt",
    key: "test_attempt",
    id: "test-one",
    value: { test_name: "Practice aptitude test", obtained_marks: 64, total_marks: 100, test_date: "2026-09-20" },
    digest: "f".repeat(64),
    evidence_level: "stated",
    source: { quote: "I got 64 out of 100 on the practice test." },
    updated_at: "2026-09-21",
  },
  {
    kind: "education",
    key: "education",
    id: "education",
    value: {
      qualification_name: "Secondary education",
      institution_name: "Community school",
      academic_status: "current",
    },
    digest: "b".repeat(64),
    evidence_level: "shown",
    source: { quote: "Current student record", file_id: "document" },
    updated_at: "2026-10-18",
  },
];
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
