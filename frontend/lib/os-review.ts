/** PAI OS review queue (P2-T5, R-25, R-42, R-72, R-75). Reviewers use their own token. Staff words, not student sentences. */

export type ReviewerRole = 'checker' | 'approver' | 'admin';
export type ReviewItemKind = 'verify' | 'report' | 'change' | 'suspect_domain' | 'collect' | 'conflict' | 'import_dispute';

export interface OsReviewer {
  ref: string;
  display_name: string;
  role: ReviewerRole;
  kind: 'person' | 'ai';
  active: boolean;
}

export interface OsReviewItem {
  id: number;
  kind: ReviewItemKind;
  status: 'open' | 'closed';
  resolution: string | null;
  fact_id: number | null;
  subject: string;
  field: string | null;
  intake_term: string;
  intake_year: number | null;
  owner_ref: string;
  summary: string;
  payload: Record<string, unknown>;
  batch_ref: string | null;
  join_count: number;
  opened_by: string;
  created_at: string;
  closed_at: string | null;
}

export interface OsReviewFact {
  id: number;
  scope: string;
  ref: string;
  field: string;
  value: unknown;
  quote: string;
  url: string;
  status: 'unconfirmed' | 'confirmed' | 'verified' | 'stale';
  checked_at: string;
  intake_term: string;
  intake_year: number;
  owner_ref: string;
  fact_class: string;
  high_stakes: boolean;
  read_method: string | null;
  language: string | null;
}

export interface OsReviewSnapshot {
  url: string;
  fetched_at: string;
  read_method: string;
  text: string;
  truncated: boolean;
  quote_found: boolean;
}

export interface OsReviewFile {
  id: number;
  filename: string;
  content_type: string;
  size: number;
  uploaded_by: string;
}

export interface OsReviewEntry {
  id: number;
  reviewer: string;
  kind: string;
  step: 'check' | 'approve' | 'collect';
  outcome: string;
  corrected_value: unknown;
  corrected_quote: string | null;
  note: string | null;
}

export interface OsReviewDetail {
  item: OsReviewItem;
  fact: OsReviewFact | null;
  snapshot: OsReviewSnapshot | null;
  files: OsReviewFile[];
  reviews: OsReviewEntry[];
  my_review: { step: string; outcome: string } | null;
}

export interface OsReviewResult {
  item_id: number;
  item_status: 'open' | 'closed';
  resolution: string | null;
  fact_status?: string | null;
}

export const KIND_LABELS: Record<ReviewItemKind, string> = {
  verify: 'Check a fact',
  report: 'Reported by a student',
  change: 'Source changed',
  suspect_domain: 'Suspect website',
  collect: 'Collect by hand',
  conflict: 'Disagreement',
  import_dispute: 'Disputed spreadsheet row',
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind as ReviewItemKind] ?? kind.replace(/_/g, ' ');
}

export const RESOLUTION_LABELS: Record<string, string> = {
  verified: 'Verified', demoted: 'Marked wrong', corrected: 'Corrected', rejected: 'Rejected', unclear: 'Unclear',
  collected: 'Collected', void: 'Fact changed', resolved: 'Resolved', dismissed: 'Dismissed',
};

export function resolutionLabel(resolution: string | null): string {
  return resolution ? RESOLUTION_LABELS[resolution] ?? resolution : '';
}

/** The step a reviewer's role gives on a verify item; an admin chooses. */
export function stepsFor(role: ReviewerRole): Array<'check' | 'approve'> {
  return role === 'checker' ? ['check'] : role === 'approver' ? ['approve'] : ['check', 'approve'];
}

/**
 * Where the quote sits in the page text, ignoring differences in white space (the page was normalised before the quote
 * was matched). A quote of several pieces ("..." or line breaks) is marked piece by piece. Returns [start, end) pairs.
 */
export function quoteRanges(text: string, quote: string): Array<[number, number]> {
  const pieces = quote.split(/\.\.\.|…|\n/).map((p) => p.trim()).filter(Boolean);
  const out: Array<[number, number]> = [];
  let from = 0;
  for (const piece of pieces) {
    const pattern = piece.split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
    const re = new RegExp(pattern, 'i');
    const m = re.exec(text.slice(from));
    if (!m) continue;
    out.push([from + m.index, from + m.index + m[0].length]);
    from += m.index + m[0].length;
  }
  return out;
}

/** The text in segments, each flagged when it is part of the quote. */
export function highlight(text: string, quote: string): Array<{ text: string; mark: boolean }> {
  const segments: Array<{ text: string; mark: boolean }> = [];
  let at = 0;
  for (const [s, e] of quoteRanges(text, quote)) {
    if (s > at) segments.push({ text: text.slice(at, s), mark: false });
    segments.push({ text: text.slice(s, e), mark: true });
    at = e;
  }
  if (at < text.length) segments.push({ text: text.slice(at), mark: false });
  return segments;
}

/** A typed value as the reviewer sees and edits it: JSON text. */
export function showValue(value: unknown): string {
  return typeof value === 'string' ? JSON.stringify(value) : JSON.stringify(value, null, 1) ?? 'null';
}

/** Reads the reviewer's JSON text back into a value; null when it is not valid JSON. */
export function parseValue(text: string): { ok: true; value: unknown } | { ok: false } {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}
