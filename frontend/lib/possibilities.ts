import type { VaultLevel } from './vault';
/** One requirement of a path checked against the student: have (green),
 * partial (amber), blocker (red) or unknown (grey). Known verdicts carry the
 * student's own words; the server turns anything uncited into unknown. */
export type FitItem = {
  label: string;
  status: 'have' | 'partial' | 'blocker' | 'unknown';
  note: string;
  evidence: string[];
};

export type PathEvidence = {
  text: string;
  item_id: string | null;
  /** A Vault level, or "source" for a researched field-note fact (a world
   * fact with its source_url), never the student's own words. */
  evidence_level?: VaultLevel | 'source' | null;
  source_label?: string | null;
  source_url?: string | null;
};

export type Possibility = {
  id: string; title: string; why: string;
  status: 'suggested' | 'exploring' | 'saved' | 'dismissed' | 'chosen';
  source?: 'mirror' | 'planner' | 'student' | 'analyzer';
  /** What the reason rests on. A Vault entry carries its evidence level and
   * where it came from (onboarding, chat, details or a document's name);
   * a notebook note carries neither. */
  evidence: PathEvidence[];
  fit?: FitItem[];
  /** The study field an analyzer path names. needs_check: the student's group
   * may qualify only with conditions; needs_group: the intermediate group a
   * Matric student would need; outdated: a kept path from before fields;
   * out_of_group: a kept field the student's current group does not open. */
  study_field?: StudyField | null;
  unknowns: string[];
};

export type StudyField = {
  key?: string;
  needs_check?: boolean;
  needs_group?: { code: string; label: string }[];
  outdated?: boolean;
  out_of_group?: boolean;
};

/** The latest path analysis, so the Paths page knows when to stop waiting. */
export type PathAnalysisStatus = { job_id: string | null; done: boolean; outcome: string | null };
