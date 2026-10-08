export interface CounselorMirror {
  intro: string;
  confidence: 'full' | 'focused' | 'light';
  dimensions: { key: string; name: string; picture: string; evidence: string; unknown: boolean }[];
  blockers: string[];
  opinion: string;
  question: string;
  roadmap_lanes: { lane: string; why: string; strengths?: string[] }[];
}

export interface CounselorMirrorDraft {
  type?: 'mirror';
  status: 'awaiting_confirmation' | 'confirmed' | 'needs_changes' | null;
  version: number | null;
  mirror?: CounselorMirror;
}
