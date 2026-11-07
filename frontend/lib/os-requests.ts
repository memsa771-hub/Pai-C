/**
 * Connection work (P1-T8, R-18, R-19, R-21): what the plan asks of the student, and the choices of a "which is right"
 * question. Types and pure helpers, free of React. Every student sentence (`how`, `label`, `new_label`, `note`) comes
 * from the server; the few words it does not send live in copy.json (`connect.requests`).
 * GET /v1/os/requests; POST /v1/os/requests/{id}/answer.
 */
import { apiRefusal } from './os-connect';
import type { OsInboxItem } from './os-inbox';

export type RequestEvidence = 'stated' | 'shown' | 'confirmed' | 'unknown';

export interface OsChoice {
  /** The question the student saw; the answer names it back. */
  ref: string;
  key: string;
  /** A short hash of the values shown; the answer names it back too. */
  seen: string;
  /** `current` | `proposed` | `new`, or `doc:<id>` for a document that holds one of the values. */
  choice: string;
  label: string;
  value: string | number;
  /** A stated value is `vault`; the host does not say chat or profile page. */
  source: { kind: 'vault' | 'document'; evidence: RequestEvidence; document_ref: string | null; as_of: string | null };
}

export interface OsRequest {
  id: number;
  task_id: number | null;
  kind: 'provide' | 'which_is_right';
  need: { kind: 'fact' | 'document'; ref: string; evidence: string };
  status: 'open' | 'answered';
  due_at: string | null;
  due_tz: string | null;
  title: string | null;
  /** How the step closes, in the server's words. */
  how: string;
  ref?: string | null;
  seen?: string | null;
  choices: OsChoice[];
  /** The student may type the right value. */
  allow_new: boolean;
  new_label: string | null;
}

/** The inbox items with their open request attached (matched by step id). No requests: the items as they are. */
export function withRequests(items: OsInboxItem[], requests: OsRequest[] | null): OsInboxItem[] {
  if (!requests || requests.length === 0) return items;
  const open = new Map(requests.filter((r) => r.status === 'open' && r.task_id !== null).map((r) => [r.task_id, r]));
  return items.map((item) => (open.has(item.id) ? { ...item, request: open.get(item.id) } : item));
}

/** Whether a body is the requests answer; anything else reads as "no requests". */
export function asRequests(body: unknown): OsRequest[] | null {
  const list = (body as { requests?: unknown } | null)?.requests;
  return Array.isArray(list) ? (list as OsRequest[]) : null;
}

/** A typed value as the API takes it: a number when it is one, else the text. */
export function typedValue(text: string): string | number {
  const t = text.trim();
  return t !== '' && Number.isFinite(Number(t)) ? Number(t) : t;
}

/** The parts of the line under a value: where it is held, how sure, and since when. Words come from copy.json. */
export function sourceParts(choice: OsChoice, words: RequestWords, locale = 'en-GB'): string[] {
  const { kind, evidence, as_of } = choice.source;
  const date = as_of ? new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(as_of)) : null;
  return [words.kinds[kind], evidence !== 'unknown' ? words.levels[evidence] : null, date ? words.asOf.replace('{date}', date) : null]
    .filter((p): p is string => !!p);
}

export interface RequestWords {
  use: string;
  kinds: Record<'vault' | 'document', string>;
  levels: Record<'stated' | 'shown' | 'confirmed', string>;
  asOf: string;
  changed: string;
  unavailable: string;
  failed: string;
}

/** The sentence for a refused answer: the server's `note` (a changed question), the unavailable line, or a plain one.
 * `reload` is true when the student must look at the list again (the question changed or is already answered). */
export function answerRefusal(err: unknown, words: RequestWords): { text: string | null; reload: boolean } {
  const r = apiRefusal(err);
  if (r.status === 409 && r.detail === 'answer_changed') return { text: r.note ?? words.changed, reload: true };
  if (r.status === 409 && (r.detail === 'already_answered' || r.detail === 'answer_elsewhere')) return { text: null, reload: true };
  if (r.status === 503) return { text: words.unavailable, reload: false };
  return { text: words.failed, reload: false };
}
