/** The Roadmap page payload (GET /v1/roadmap), computed by the backend
 * roadmap engine (backend/app/pai_c/roadmap). Reasons, needs and steps are
 * copy keys with values; the page renders them from copy.json `roadmap`. */

export type RoadmapStatus = "open" | "step" | "not_open" | "unknown";

export type RouteGroup = { code: string; label: string; route_label?: string };

/** A copy key with its values, e.g. {key: "needs_percent", min: 60, have: 55}. */
export type CopyItem = { key: string; [value: string]: unknown };

export type RouteNeed = { kind: "marks" | "bridge" | "check" | "group"; detail: Record<string, unknown> };

export type EntryTest = { name: string; body?: string; pass_percent: number | null; source?: string };

export type Verdict = {
  status: RoadmapStatus;
  reasons: CopyItem[];
  needs: RouteNeed[];
  tests: EntryTest[];
  years: number | null;
  min_percent: number | null;
  student_percent: number | null;
  confidence: "official" | "secondary" | "uncertain" | null;
  sources: string[];
  subjects?: string[];
};

export type FieldCard = {
  possibility_id: string;
  field_key: string | null;
  title: string;
  family: string | null;
  why: string;
  status: RoadmapStatus;
  verdict: Verdict;
};

export type EducationLine = {
  level: string;
  level_label: string;
  groups: RouteGroup[];
  percent: number | null;
};

export type ChosenRoute = {
  id: string;
  field_key: string;
  possibility_id?: string | null;
  title: string;
  chosen_at: string | null;
  steps: CopyItem[];
  steps_done: boolean[];
  snapshot_verdict: Verdict | null;
  live_status: RoadmapStatus;
};

export type RoadmapPage = {
  education_line: EducationLine | null;
  standing?: Record<string, unknown>;
  counts: Record<RoadmapStatus, number>;
  fields: FieldCard[];
  chosen: ChosenRoute | null;
  /** When the admission rules were last checked, "YYYY-MM". */
  rules_as_of?: string | null;
};
