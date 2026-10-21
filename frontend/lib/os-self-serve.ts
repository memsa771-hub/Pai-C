/**
 * PAI OS self-serve start and eligibility: types and pure helpers (chips, line text, choices).
 * Data comes from backend/app/os/api (Slice 4 spec §4). Kept free of React.
 *
 * Nothing here knows a country, a test or a grade scale: a line's check name, numbers and document types come from
 * the route's rules on the server. Eligibility is an estimate that warns and never blocks (spec S4-D5).
 */

import type { FactStatus } from './os-programmes';

export type Verdict = 'likely_meets' | 'likely_below' | 'needs_input' | 'unknown';

export interface OsFactRef {
  field: string;
  url: string;
  status: FactStatus;
}

export interface OsLine {
  check: string; // "grade", "language:<language>", "test"
  status: Verdict;
  have: unknown;
  need: unknown;
  provisional: boolean;
  needs: string[]; // document types whose confirmation would fill this line
  reason: string | null;
  sources: OsFactRef[];
}

export interface OsCard {
  programme_ref: string;
  verdict: Verdict;
  lines: OsLine[];
}

export interface OsRoute {
  key: string;
  version: number;
  origin: string;
  destination: string;
  level: string;
}

export interface OsRouteProgramme {
  ref: string;
  university: string;
  name: string;
  research_state: 'researched' | 'being_researched';
  requested_by_student: boolean;
  confirmed_facts: number;
  card: OsCard | null;
}

export interface OsSuggestion {
  programme_ref: string;
  university: string;
  name: string;
  confirmed_facts: number;
}

export interface OsEligibility {
  card: OsCard | null;
  suggestions: OsSuggestion[];
}

export interface OsChoice {
  programme_ref: string;
  rank: number;
}

export interface OsSelfPlan {
  plan_id: number;
  revision: number;
  status: string;
  programmes: OsChoice[];
}

export interface OsNote {
  id: number;
  programme_ref: string;
  verdict: Verdict;
  payload: {
    plan_id?: number;
    programme_ref: string;
    verdict: Verdict;
    previous?: Verdict;
    lines: OsLine[];
    suggestions: string[];
  };
  created_at: string;
}

export interface OsProgrammeRequest {
  route: string;
  intake_year: number;
  university: string;
  name: string;
  url: string;
}

export const MAX_CHOICES = 10;

export const PROVISIONAL_TEXT =
  "Estimated with a typical minimum passing grade; upload your university's minimum-passing-grade letter for an accurate result.";

export const CARD_FOOTER = 'An estimate, not a decision: the university decides.';

const CHIPS: Record<Verdict, string> = {
  likely_meets: 'likely meets',
  likely_below: 'check this',
  needs_input: 'needs your documents',
  unknown: 'being researched',
};

/** The chip for a verdict, or for a programme still being researched. */
export function chipLabel(p: { research_state?: string; card: OsCard | null } | Verdict): string {
  if (typeof p === 'string') return CHIPS[p] ?? p;
  if (p.research_state === 'being_researched' || p.card === null) return CHIPS.unknown;
  return CHIPS[p.card.verdict] ?? p.card.verdict;
}

const CHIP_TONE: Record<Verdict, string> = {
  likely_meets: 'bg-emerald-100 text-emerald-900',
  likely_below: 'bg-amber-100 text-amber-900',
  needs_input: 'bg-muted text-muted-foreground',
  unknown: 'bg-muted text-muted-foreground',
};

export function chipTone(v: Verdict): string {
  return CHIP_TONE[v] ?? CHIP_TONE.unknown;
}

function words(s: string): string {
  const t = s.replace(/_/g, ' ').trim();
  return t.charAt(0).toUpperCase() + t.slice(1);
}

/** "grade" -> "Grade", "language:english" -> "English", "test" -> "Admission test". */
export function checkLabel(check: string): string {
  if (check.startsWith('language:')) return words(check.slice('language:'.length));
  if (check === 'test') return 'Admission test';
  return words(check);
}

/** "min_passing_grade_letter" -> "min passing grade letter". */
export function docLabel(docType: string): string {
  return docType.replace(/_/g, ' ');
}

export function valueText(v: unknown): string {
  if (v === null || v === undefined) return '—';
  if (Array.isArray(v)) return v.map(valueText).join(' or ');
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
  return String(v).replace(/_/g, ' ');
}

/** One line of a card in plain words, with its numbers. */
export function lineText(line: OsLine): string {
  if (line.status === 'unknown') return 'Not stated yet: being researched';
  if (line.status === 'needs_input') {
    if (line.reason === 'open_finding') return 'Resolve the mismatch in your documents first';
    if (line.reason === 'no_proof_type') return `Needs proof of ${valueText(line.need)}`;
    const docs = line.needs.map(docLabel);
    return docs.length ? `Needs your ${docs.join(' or ')}` : 'Needs your documents';
  }
  if (line.have === null || line.have === undefined) {
    const none = line.need === null || line.need === undefined || String(line.need).toLowerCase() === 'none';
    return none ? 'Not required' : `Required: ${valueText(line.need)}`;
  }
  return `Yours ${valueText(line.have)} · needs ${valueText(line.need)}`;
}

/** Adds a programme (up to MAX_CHOICES) or removes it. */
export function toggleChoice(choices: string[], ref: string): string[] {
  if (choices.includes(ref)) return choices.filter((r) => r !== ref);
  return choices.length >= MAX_CHOICES ? choices : [...choices, ref];
}

/** Moves one choice up (-1) or down (+1) in the ranking. */
export function moveChoice(choices: string[], index: number, delta: number): string[] {
  const to = index + delta;
  if (to < 0 || to >= choices.length) return choices;
  const next = [...choices];
  [next[index], next[to]] = [next[to], next[index]];
  return next;
}

/** The question asked before a swap: the student's OK first (spec S4-D5). */
export function swapPrompt(outName: string, inName: string): string {
  return `Swap ${outName} for ${inName}? The steps you have not started for ${outName} will be removed from your plan.`;
}

/** A friendly message for a failed request (the API sends 429 over the daily cap). */
export function requestErrorText(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  if (msg.startsWith('API 429')) return 'You can request up to 3 programmes a day. Please try again tomorrow.';
  if (msg.startsWith('API 422')) return 'Please check the details: the page must be an https:// address.';
  return 'That request did not go through. Please try again.';
}
