import type { Possibility } from "./possibilities";
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
  level?: string;
};
export type LivingPicture = {
  coverage: Record<string, { covered: boolean; item_count: number }>;
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
  picture: Record<string, { text: string; evidence: string[] }> | null;
  mirror_status: string | null;
  moments: Record<string, string>;
  ratings: {
    version: number;
    understood: number;
    before: number | null;
    after: number | null;
  }[];
};
export type ProfileCard = {
  kind: string;
  key: string;
  id: string;
  value: unknown;
  digest: string;
  evidence_level: "stated" | "shown" | "confirmed";
  source: Record<string, unknown>;
  updated_at: string;
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
