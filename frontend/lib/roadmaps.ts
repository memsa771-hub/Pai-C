export type RoadmapStatus = 'generating' | 'ready' | 'needs_info' | 'failed' | 'stale';
export type RoadmapOrigin = 'stated_goal' | 'alternative' | 'family_wish' | 'student_added' | 'operator_suggested';
export type FitLevel = 'strong' | 'partial' | 'weak' | 'not_possible_yet' | 'unconfirmed' | null;

export interface RoadmapGap {
  field?: string;
  status?: 'met' | 'fixable' | 'blocking' | 'unknown';
  reason?: string;
  source_url?: string;
  remediation?: { action?: string; source_url?: string; time_to_fix?: string };
  time_to_fix?: string;
}

export interface Roadmap {
  id: string;
  journey_id: string;
  goal_id: string | null;
  origin: RoadmapOrigin;
  title: string;
  route: Record<string, unknown>;
  fit_level: FitLevel;
  fit_dimensions: Record<string, { level: string; reason: string; source: string | null }>;
  gaps: RoadmapGap[];
  steps: Array<Record<string, unknown>>;
  total_cost: { amount?: number; currency?: string; basis?: string; status?: string; reason?: string; components?: unknown[] } | null;
  time_to_start: string | null;
  risks: string[];
  scholarships: Array<{ title: string; eligibility?: { quote?: string } | null;
    amount?: { quote?: string } | null; deadline?: { quote?: string } | null;
    source_url: string; checked_at: string; status: string; reason?: string }>;
  sources: Array<{ url: string; checked_at: string; status?: string }>;
  requirement_set_id?: string | null;
  generation_status: RoadmapStatus;
  stale_reason: string | null;
  execution_run_id: string | null;
  version: number;
  new?: boolean;
  favorite: boolean;
  exploring: boolean;
  dismissed_at: string | null;
  chosen_at: string | null;
  focused_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface RoadmapEvidence {
  id: string;
  status: 'verified' | 'unconfirmed' | 'expired';
  version: number;
  rules: Array<{ field?: string; value?: unknown; quote?: string; source_url?: string; checked_at?: string }>;
  fees: Record<string, { value?: unknown; quote?: string; source_url?: string; checked_at?: string }>;
  deadlines: Record<string, { value?: unknown; quote?: string; source_url?: string; checked_at?: string }>;
  verification_checks: Record<string, { passed: boolean; reason?: string | null }>;
  source_url: string;
  checked_at: string;
}

export interface RoadmapDetail extends Roadmap {
  evidence: RoadmapEvidence | null;
  evidence_history: Array<{ version: number; status: string; checked_at: string; source_url: string }>;
}

export interface StudentRequest {
  id: string;
  source: 'research' | 'os';
  execution_run_id: string | null;
  item_key: string;
  reason: string;
  accepts_upload: boolean;
  status: 'open' | 'answered' | 'withdrawn';
  created_at: string;
  asked_at: string | null;
  answered_at: string | null;
}

export interface DecisionRecord {
  id: string;
  journey_id: string;
  roadmap_id: string;
  roadmap_version: number;
  confirmed_summary: Record<string, unknown>;
  real_objective: string | null;
  accepted_gaps: RoadmapGap[];
  accepted_risks: string[];
  assumptions: string[];
  choice_channel: 'chat' | 'voice' | 'roadmaps';
  chosen_at: string;
}

export interface CounselorGoalSummary {
  status: 'awaiting_confirmation' | 'confirmed' | null;
  summary: Record<string, { value: unknown; status: string; student_words?: string }>;
  version: number | null;
}

export interface CustomRoadmapGoal {
  title: string;
  country?: string;
  level?: string;
  field?: string;
  why?: string;
}
