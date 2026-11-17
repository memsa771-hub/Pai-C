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
  /** A held value is `vault`; the proposed side with no document is `said` (chat or profile page: the host does not say). */
  source: { kind: 'vault' | 'document' | 'said'; evidence: RequestEvidence; document_ref: string | null; as_of: string | null };
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

/** A typed value as the API takes it. `numeric` (the values on the question are numbers): plain decimal digits only,
 * sent as a number; anything else (hex, exponent, spaces inside) is null. Otherwise the trimmed text. Null = not valid. */
export function typedValue(text: string, numeric = true): string | number | null {
  const t = text.trim();
  if (t === '') return null;
  if (!numeric) return t;
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : null;
}

/** Whether the right value is a number: the question shows numbers, or shows none (a value above its total). */
export function isNumeric(request: OsRequest): boolean {
  return request.choices.length === 0 || request.choices.some((c) => typeof c.value === 'number');
}

/** The templates of the steps PAI adds for a need (the inbox item carries no template, only its instance key). */
const REQUEST_PREFIXES = ['provide@', 'which_is_right@', 'result_expected@'];

/** A step that asks for the student's data, from the request when it is there, else from its key: such a step has no
 * "Mark as done", also when the requests could not be loaded. */
export function isRequestItem(item: OsInboxItem): boolean {
  return !!item.request || REQUEST_PREFIXES.some((p) => item.instance_key.startsWith(p));
}

/** The parts of the line under a value: where it is held (unless the label already says so), how sure, and since when. */
export function sourceParts(choice: OsChoice, words: RequestWords, locale = 'en-GB'): string[] {
  const { kind, evidence, as_of } = choice.source;
  const date = as_of ? new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(as_of)) : null;
  const where = words.kinds[kind];
  return [where && where.toLowerCase() !== choice.label.trim().toLowerCase() ? where : null,
    evidence !== 'unknown' ? words.levels[evidence] : null, date ? words.asOf.replace('{date}', date) : null]
    .filter((p): p is string => !!p);
}

export interface RequestWords {
  use: string;
  kinds: Record<'vault' | 'document' | 'said', string>;
  levels: Record<'stated' | 'shown' | 'confirmed', string>;
  asOf: string;
  pending: string;
  gone: string;
  unavailable: string;
  failed: string;
}

/** The sentence for a refused answer: the server's `note` (a changed question, with the approved sentence), the
 * unavailable line, "gone" for a 404, or the plain one. `reload` is true when the student must look at the list again. */
export function answerRefusal(err: unknown, words: RequestWords): { text: string | null; reload: boolean } {
  const r = apiRefusal(err);
  if (r.status === 409 && r.detail === 'answer_changed') return { text: r.note ?? words.failed, reload: true };
  if (r.status === 409 && (r.detail === 'already_answered' || r.detail === 'answer_elsewhere')) return { text: null, reload: true };
  if (r.status === 404) return { text: words.gone, reload: true };
  if (r.status === 422) return { text: r.note ?? words.failed, reload: false };
  if (r.status === 503) return { text: words.unavailable, reload: false };
  return { text: words.failed, reload: false };
}

/** The server's sentence for a refused "Mark as done" (409, e.g. `answer_required`), else null. */
export function completeRefusal(err: unknown): string | null {
  const r = apiRefusal(err);
  return r.status === 409 && r.detail ? r.detail : null;
}
