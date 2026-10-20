/**
 * PAI OS programme facts: types and pure helpers (labels, value formatting, the "Ask the university" draft).
 * Data comes from GET /v1/os/programmes (backend/app/os/api, Slice 2 spec §4.8-4.9). Kept free of React.
 *
 * Nothing here knows a country or a field name: values are formatted by their shape, and a programme's
 * "date facts" are the facts whose value is a {date}.
 */

export type FactStatus = 'confirmed' | 'unconfirmed' | 'stale';

export interface OsFact {
  field: string;
  value: unknown;
  status: FactStatus;
  source_url: string | null;
  quote: string | null;
  checked_at: string;
  conflict_note: string | null;
}

export interface OsProgramme {
  ref: string;
  name: string;
  university: string | null;
  intake_year: number;
  facts: OsFact[];
  /** The route's "Ask the university" template, when the API sends it (otherwise DEFAULT_DRAFT_EMAIL). */
  draft_email?: string;
}

const STATUS_LABELS: Record<FactStatus, string> = {
  confirmed: '✓ checked',
  unconfirmed: '⚠ unconfirmed',
  stale: '⚠ needs re-check',
};

export function statusLabel(status: FactStatus): string {
  return STATUS_LABELS[status] ?? status;
}

/** "deadline_close" -> "Deadline close". */
export function fieldLabel(field: string): string {
  const words = field.replace(/_/g, ' ').trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function formatDate(iso: string): string {
  const d = new Date(`${iso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(d);
}

/** A fact value of any shape, as one short line. */
export function formatFactValue(value: unknown): string {
  if (value === null || value === undefined) return 'not stated';
  if (typeof value === 'string') return value.replace(/_/g, ' ');
  if (typeof value === 'number') return String(value);
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (Array.isArray(value)) return value.length === 0 ? 'none' : value.map(formatFactValue).join(', ');
  if (typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    if (typeof obj.date === 'string') return formatDate(obj.date);
    const parts = Object.entries(obj)
      .filter(([, v]) => v !== null && v !== undefined)
      .map(([k, v]) => `${k.replace(/_/g, ' ')} ${formatFactValue(v)}`);
    return parts.length ? parts.join(' · ') : 'not stated';
  }
  return String(value);
}

export function isDateFact(f: OsFact): boolean {
  return typeof f.value === 'object' && f.value !== null && typeof (f.value as { date?: unknown }).date === 'string';
}

const WEAKNESS: Record<FactStatus, number> = { confirmed: 0, unconfirmed: 1, stale: 2 };

/** The weakest status among a programme's date facts: the label its dated inbox items carry. */
export function dateFactStatus(programme: OsProgramme): FactStatus | null {
  const dates = programme.facts.filter(isDateFact);
  if (dates.length === 0) return null;
  return dates.reduce<FactStatus>((worst, f) => (WEAKNESS[f.status] > WEAKNESS[worst] ? f.status : worst), 'confirmed');
}

export function checkedLabel(iso: string): string {
  return `checked ${formatDate(iso.slice(0, 10))}`;
}

/** The same text as the research profile's draft_email; used until the API sends the route's own. */
export const DEFAULT_DRAFT_EMAIL = `Dear admissions team,

I am a prospective student from outside the EU and I plan to apply to {programme} at {university}
for the {intake} intake. Could you please confirm: {question}

Your website says: "{quote}" ({url}). Is this still correct for {intake}?

Thank you very much.`;

/** The "Ask the university" draft for one fact. The student copies and sends it; the OS never sends it. */
export function fillDraft(template: string | undefined, programme: OsProgramme, f: OsFact): string {
  const values: Record<string, string> = {
    programme: programme.name,
    university: programme.university ?? 'your university',
    intake: String(programme.intake_year),
    question: `${fieldLabel(f.field)}: ${formatFactValue(f.value)}?`,
    quote: f.quote ?? '',
    url: f.source_url ?? '',
  };
  return (template ?? DEFAULT_DRAFT_EMAIL).replace(/\{(\w+)\}/g, (m, key: string) => values[key] ?? m);
}
