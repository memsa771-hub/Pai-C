export type RoadmapStatus = 'generating' | 'ready' | 'needs_info' | 'failed' | 'stale';
export type RoadmapOrigin = 'stated_goal' | 'alternative' | 'student_added' | 'operator_suggested';
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
  total_cost: { amount?: number; currency?: string; basis?: string } | null;
  time_to_start: string | null;
  risks: string[];
  sources: Array<{ url: string; checked_at: string }>;
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

export interface CustomRoadmapGoal {
  title: string;
  country?: string;
  level?: string;
  field?: string;
  why?: string;
}
