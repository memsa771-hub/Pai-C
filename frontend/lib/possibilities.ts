/** One requirement of a path checked against the student: have (green),
 * partial (amber), blocker (red) or unknown (grey). Known verdicts carry the
 * student's own words; the server turns anything uncited into unknown. */
export type FitItem = {
  label: string;
  status: 'have' | 'partial' | 'blocker' | 'unknown';
  note: string;
  evidence: string[];
};

export type Possibility = {
  id: string; title: string; why: string;
  status: 'suggested' | 'exploring' | 'saved' | 'dismissed' | 'chosen';
  source?: 'mirror' | 'planner' | 'student' | 'analyzer';
  evidence: { text: string; item_id: string | null }[];
  fit?: FitItem[];
  /** The study field an analyzer path names. needs_check: the student's group
   * may qualify only with conditions; needs_group: the intermediate group a
   * Matric student would need; outdated: a kept path from before fields. */
  study_field?: StudyField | null;
  unknowns: string[]; roadmap_id: string | null;
};

export type StudyField = {
  key?: string;
  needs_check?: boolean;
  needs_group?: { code: string; label: string }[];
  outdated?: boolean;
};
