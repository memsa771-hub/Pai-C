/** PAI OS statements (Slice 5 spec §4, §5): the interview, the drafts, the student's edits and approval. */

export interface OsInterviewItem {
  id: string;
  prompt: string;
  hint: string;
  required: boolean;
  answer: string;
  /** Asked by the reviewer; open follow-ups come first. */
  follow_up: boolean;
}

export interface OsInterview {
  route: string;
  questions: OsInterviewItem[];
  missing: string[];
}

export interface OsStatementVersion {
  number: number;
  text: string;
  author: 'writer' | 'student';
  words: number;
  critic: { scores?: Record<string, number>; fixes?: string[]; ok?: boolean } | null;
  flags: string[];
  limit_words: number | null;
  created_at: string;
}

export interface OsApproval {
  version: number;
  sha256: string;
  approved_at: string;
}

export type OsStatementKind = 'sop' | 'cv';

export interface OsStatement {
  id: number;
  kind: OsStatementKind;
  programme_ref: string | null;
  status: 'empty' | 'drafting' | 'draft' | 'needs_answers' | 'failed' | 'budget' | 'approved';
  version: OsStatementVersion | null;
  approval: OsApproval | null;
}

export const NOT_FOUND_COPY = 'We could not find this in your answers or profile';
export const APPROVED_COPY = 'This is the text that goes in your application';

/** "Statement of purpose for MSc Example": a programme by its name, never its internal ref (Slice 9 Task 11). */
export function kindLabel(kind: OsStatementKind, programmeRef: string | null = null,
                          names: Record<string, string> = {}): string {
  if (kind === 'cv') return 'CV';
  if (!programmeRef) return 'Statement of purpose';
  return `Statement of purpose for ${names[programmeRef] ?? 'one of your programmes'}`;
}

/** Programme ref -> name, from the statements page's programmes. */
export function programmeNames(programmes: OsProgrammeRules[]): Record<string, string> {
  return Object.fromEntries(programmes.filter((p) => p.name).map((p) => [p.programme_ref, p.name as string]));
}

export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

/** "812 / 1,000 words", or the count alone when there is no limit. */
export function countLabel(words: number, limit: number | null): string {
  const n = words.toLocaleString('en-US');
  return limit ? `${n} / ${limit.toLocaleString('en-US')} words` : `${n} words`;
}

export function overBy(words: number, limit: number | null): string | null {
  if (!limit || words <= limit) return null;
  const n = words - limit;
  return `Over by ${n} word${n === 1 ? '' : 's'}`;
}

/** "3 of 8 answered": the required questions answered. */
export function progressLabel(items: OsInterviewItem[]): string {
  const required = items.filter((i) => i.required && !i.follow_up);
  const done = required.filter((i) => i.answer.trim()).length;
  return `${done} of ${required.length} answered`;
}

export function shortHash(sha256: string): string {
  return sha256.slice(0, 12);
}

export interface Segment {
  text: string;
  flagged: boolean;
}

/** Splits the text so each flagged phrase (every occurrence, case-insensitive) is its own segment. */
export function segments(text: string, flags: string[]): Segment[] {
  const phrases = [...new Set(flags.filter((f) => f.trim()))].sort((a, b) => b.length - a.length);
  if (phrases.length === 0) return [{ text, flagged: false }];
  const escaped = phrases.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const re = new RegExp(`(${escaped.join('|')})`, 'gi');
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ text: text.slice(last, at), flagged: false });
    out.push({ text: m[0], flagged: true });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), flagged: false });
  return out;
}

export function statusLabel(s: OsStatement): string {
  switch (s.status) {
    case 'empty': return 'not started';
    case 'drafting': return 'being written…';
    case 'draft': return 'draft ready';
    case 'needs_answers': return 'answer the new questions';
    case 'failed': return 'could not write: try again';
    case 'budget': return "paused: this month's writing budget is used up; try again later";
    case 'approved': return 'approved ✓';
  }
}

/** One plan programme's statement rules: does it ask for its own statement, and with what limit and prompt. */
export interface OsProgrammeRules {
  programme_ref: string;
  name?: string | null; // from the programme store (Slice 9 Task 11)
  university?: string | null;
  needed: boolean;
  limit_words: number | null;
  limit_chars: number | null;
  prompt: string | null;
  source: 'research' | 'student' | 'default';
  status: string | null;
}

export interface OsStatements {
  statements: OsStatement[];
  programmes: OsProgrammeRules[];
}

export function rulesLabel(r: OsProgrammeRules): string {
  if (!r.needed) return 'Uses your main statement';
  const limit = r.limit_chars ? `${r.limit_chars.toLocaleString('en-US')} characters`
    : r.limit_words ? `${r.limit_words.toLocaleString('en-US')} words` : 'no stated limit';
  const from = r.source === 'research'
    ? (r.status === 'confirmed' ? "from the programme's pages" : "from the programme's pages, not yet confirmed")
    : 'from what you pasted';
  return `Asks for its own statement: ${limit} (${from})`;
}
