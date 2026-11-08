/**
 * PAI OS coverage dashboard (P2-T9, R-34, R-35, R-66). Staff words, not student sentences. Data comes from
 * GET /v1/os/admin/coverage?intake= and the admin intake list.
 */

export type IntakeState = 'planned' | 'open' | 'current' | 'closed';

export interface OsIntake {
  id: number;
  region: string;
  family: string;
  term: string;
  year: number;
  state: IntakeState;
  gate_passed_at: string | null;
}

export interface OsGateItem { gate?: string; code: string; subject: string; detail: string }
export interface OsGateReading { gate: 'a' | 'b' | 'c' | 'd'; title: string; green: boolean; checked: number; items: OsGateItem[] }

export interface OsCoverageList {
  list_id: string; name: string; region: string | null; published: number | null; loaded: number; count_confirmed: boolean;
}

export interface OsCoverageRow {
  institution_type: string;
  institutions: number;
  listed: number;
  researched: number;
  verified: number;
  lists: OsCoverageList[];
  hs_verified: number;
  hs_not_confirmed: number;
  hs_missing: number;
  not_readable: number;
}

export interface OsWorkload {
  institutions: number;
  high_stakes_facts: number;
  high_stakes_per_institution: number;
  not_verified: number;
  checks_needed: number;
  checks_left: number;
  rows_per_hour: number | null;
  hours_left: number | null;
  days_left: number | null;
}

export interface OsCoverage {
  intake: OsIntake;
  green: boolean;
  readings: OsGateReading[];
  rows: OsCoverageRow[];
  suspect_domains: string[];
  open_review_items: Record<string, number>;
  workload: OsWorkload;
}

export const ITEM_LABELS: Record<string, string> = {
  no_list: 'No official list',
  count_unconfirmed: 'Published count not confirmed',
  list_incomplete: 'List not fully loaded',
  list_over: 'More loaded than published',
  missing: 'Missing',
  not_verified: 'Not verified',
  no_link: 'Not confirmed and no official link',
};

export function itemLabel(code: string): string {
  return ITEM_LABELS[code] ?? code;
}

export const GATE_NAMES: Record<string, string> = {
  a: 'Denominator',
  b: 'Verified floor',
  c: 'Everything else',
  d: 'No online information',
};

/** "12 of 20 loaded (60%)", "no published count" - a list line. */
export function listProgress(list: OsCoverageList): string {
  if (list.published == null) return `${list.loaded} loaded, no published count`;
  const pct = list.published ? Math.round((list.loaded / list.published) * 100) : 0;
  return `${list.loaded} of ${list.published} loaded (${pct}%)${list.count_confirmed ? '' : ', count not confirmed'}`;
}

/** The workload as one line; says so when nothing has been measured yet. */
export function workloadLine(w: OsWorkload): string {
  const base = `${w.not_verified} rows left, ${w.checks_left} checks`;
  if (w.hours_left == null) return `${base}; no review rate measured yet`;
  return `${base}; about ${w.hours_left} h at ${w.rows_per_hour} rows/h${w.days_left != null ? ` (${w.days_left} working days)` : ''}`;
}

export function intakeLabel(i: OsIntake): string {
  return `${i.region} / ${i.family} / ${i.term} ${i.year} (${i.state})`;
}

/** The failing items out of an `API 409: {...}` error from making an intake current; [] when there are none to read. */
export function failingFromError(e: unknown): OsGateItem[] {
  const text = e instanceof Error ? e.message : '';
  const at = text.indexOf('{');
  if (at < 0) return [];
  try {
    const failing = (JSON.parse(text.slice(at)) as { detail?: { failing?: OsGateItem[] } }).detail?.failing;
    return Array.isArray(failing) ? failing : [];
  } catch {
    return [];
  }
}
