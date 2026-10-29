/** The Roadmap page payload (GET /v1/roadmap), computed by the backend
 * roadmap engine (backend/app/pai_c/roadmap). Reasons, needs and steps are
 * copy keys with values; the page renders them from copy.json `roadmap`. */

import type { VaultLevel } from "./vault";

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

export type StepStatus = "done" | "half" | "not";

/** One step of a field's route, coloured from the Vault (backend roadmap/steps.py):
 * done green, half yellow, not red. The evidence badge shows the level apart
 * from the colour, so a step done on a stated fact reads "done · stated". */
export type RouteStep = {
  key: string;
  kind?: string;
  label_key: string;
  values: Record<string, unknown>;
  status: StepStatus;
  colour?: "green" | "yellow" | "red";
  evidence?: { id: string | null; level: VaultLevel; source_label: string } | null;
  rule?: { source: string; confidence: "official" | "secondary" | "uncertain" | null } | null;
  manual_done?: boolean;
  /** The student may tick it: set by the backend only where the Vault is silent. */
  tickable?: boolean;
};

/** A dated calendar event behind the estimate; month null is "date not confirmed". */
export type TimeBasis = {
  step: string | null;
  event_key: string | null;
  month: number | null;
  year: number | null;
  source: string | null;
  confidence: string | null;
};

/** How long, from the academic calendar (backend roadmap/timeline.py). */
export type RouteTime = {
  to_entry_months: number | null;
  to_finish_years: number | null;
  next_intake: { label: string; start_month: number; year: number } | null;
  degree_years?: number | null;
  basis: TimeBasis[];
  confidence: "official" | "secondary" | "uncertain";
};

export type FieldCard = {
  possibility_id: string;
  field_key: string | null;
  title: string;
  family: string | null;
  why: string;
  status: RoadmapStatus;
  verdict: Verdict;
  steps?: RouteStep[];
  time?: RouteTime | null;
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
  /** The live route with the student's ticks applied. */
  steps: RouteStep[];
  time?: RouteTime | null;
  /** The route as it was at choose time. */
  snapshot_steps?: Pick<RouteStep, "key" | "label_key" | "values" | "status">[];
  /** Keys of the steps the student ticked. */
  steps_done: string[];
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
