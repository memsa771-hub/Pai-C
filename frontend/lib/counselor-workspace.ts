import type { Possibility } from "./possibilities";
import type { MirrorPicture, MirrorUnknown } from "./mirror";
export type EvidenceItem = {
  id?: string;
  key?: string;
  value?: unknown;
  evidence?: string;
  role?: string;
  wish?: string;
  worry?: string;
  concern?: string;
  capability_status?: string;
  kind?: string;
  level?: string;
  category?: string;
};
export type LivingPicture = {
  sections?: Record<string, EvidenceItem[]>;
  coverage: Record<string, {
    covered: boolean;
    item_count: number;
    min_items?: number;
    last_confirmed?: string | null;
    /** Strongest public evidence level in the area; null when there is none. */
    evidence?: "stated" | "shown" | "confirmed" | null;
  }>;
  personal: {
    world: Record<string, EvidenceItem[]>;
    self: EvidenceItem[];
    source: EvidenceItem[];
    pressures: { items: EvidenceItem[] };
    sure: {
      score: number | null;
      history: { score: number | null; asked_at: string }[];
    };
  };
  capabilities: EvidenceItem[] | Record<string, EvidenceItem[]>;
  academic: { records: Record<string, Record<string, unknown>[]> };
  /** The Mirror state card's header, unknowns, text and readiness. */
  picture: MirrorPicture | null;
  /** How complete the Vault is: areas known of the total, and what is still unknown. */
  completeness?: { known: number; total: number; unknowns: MirrorUnknown[] };
  moments: Record<string, string>;
  /** Server-owned Counselor stage (IDENTITY … CHOSEN); null before a journey exists. */
  stage?: string | null;
  /** Old certainty ratings; the backend now sends an empty list. */
  ratings?: {
    version: number;
    understood: number;
    before: number | null;
    after: number | null;
  }[];
};
export type FactCard = {
  id: string;
  label?: string;
  field_key?: string;
  choices: string[];
  input?: string;
  prefill?: string;
  quote?: string;
  record_id?: string;
  education_id?: string;
};
export type PathResult = {
  possibility: Possibility;
  status: string;
  /** The Vault changed since this explanation was written. */
  stale?: boolean;
  path: Record<string, unknown> | null;
  facts: Record<string, unknown>[];
  missing: unknown[];
};
export type Program = {
  opportunity_id: string;
  title: string;
  status: string;
  source_url: string;
  checked_at: string;
  rules: Record<string, unknown>[];
  fees: Record<string, unknown>;
  eligibility: {
    label: string;
    gaps: unknown[];
    route: Record<string, unknown>[];
  };
};
export type Programs = {
  status: string;
  programs: Program[];
  missing: string[];
};
export type CounselorHealth = {
  planner_lag_alert: boolean;
  planner_lag_seconds: number;
  fallbacks: Record<string, number>;
};
