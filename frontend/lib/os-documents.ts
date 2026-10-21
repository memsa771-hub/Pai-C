/**
 * PAI OS documents: types and pure helpers (status labels, finding text). Data comes from GET /v1/os/documents
 * (backend/app/os/api, Slice 3 spec §4-5). Kept free of React.
 *
 * Nothing here knows a document type: the types and their labels come from the API (`doc_types`), and field
 * names are shown by their generic label.
 */

import { fieldLabel } from './os-programmes';

export type DocStatus = 'uploaded' | 'reading' | 'read' | 'needs_student' | 'confirmed' | 'failed' | 'deleted';
export type FieldCheck = 'ok' | 'check_failed' | 'missing';

export interface OsDocType {
  key: string;
  label: string;
}

export interface OsDocField {
  field: string;
  value_read: unknown;
  check: FieldCheck;
  reasons: string[];
  value_confirmed: unknown;
}

export interface OsFindingItem {
  document_id: number;
  value: string;
}

export interface OsFinding {
  id: number;
  kind: 'variant' | 'mismatch';
  field: string;
  items: OsFindingItem[];
  status: 'open' | 'resolved';
  resolution: unknown;
}

export interface OsDocument {
  id: number;
  doc_type: string;
  filename: string;
  status: DocStatus;
  detected_type: string | null;
  pages: number | null;
  error: string | null;
  created_at: string;
  read_at: string | null;
  confirmed_at: string | null;
  fields: OsDocField[];
  findings: OsFinding[];
}

export interface OsDocuments {
  documents: OsDocument[];
  findings: OsFinding[];
  doc_types: OsDocType[];
}

export interface OsProfileValue {
  key: string;
  value: unknown;
  source_document_id: number | null;
  confirmed_at: string;
}

/** What the upload control accepts (the API checks the bytes; this only filters the picker). */
export const ACCEPT = 'application/pdf,image/jpeg,image/png,image/webp,.jfif';

const STATUS_LABELS: Record<DocStatus, string> = {
  uploaded: 'waiting to be read',
  reading: 'reading…',
  read: 'read',
  needs_student: 'check the type',
  confirmed: 'confirmed ✓',
  failed: 'could not read',
  deleted: 'deleted',
};

export function docStatusLabel(d: OsDocument): string {
  return STATUS_LABELS[d.status] ?? d.status;
}

export function checkFailedCount(d: OsDocument): number {
  return d.fields.filter((f) => f.check === 'check_failed').length;
}

/** Whether the student can open the document to check and confirm its values. */
export function canConfirm(d: OsDocument): boolean {
  return d.status === 'read' || d.status === 'needs_student' || d.status === 'confirmed';
}

export function typeLabel(key: string, types: OsDocType[]): string {
  return types.find((t) => t.key === key)?.label ?? fieldLabel(key);
}

const FINDING_FIELDS: Record<string, string> = {
  full_name: 'name',
  father_name: "father's name",
  date_of_birth: 'date of birth',
};

/** 'Your name differs: passport "MUHAMMAD ALI", degree certificate "Mohammad Ali". Which is right?' */
export function findingText(f: OsFinding, docs: OsDocument[], types: OsDocType[]): string {
  const what = FINDING_FIELDS[f.field] ?? fieldLabel(f.field).toLowerCase();
  const where = f.items.map((i) => {
    const d = docs.find((x) => x.id === i.document_id);
    const label = d ? typeLabel(d.doc_type, types).toLowerCase() : 'a document';
    return `${label} "${i.value}"`;
  });
  return `Your ${what} differs: ${where.join(', ')}. Which is right?`;
}

/** The value a field starts with in the confirm form: the confirmed value if there is one, else the value read. */
export function startValue(f: OsDocField): string {
  const v = f.value_confirmed ?? f.value_read;
  return v === null || v === undefined ? '' : String(v);
}

/** The form's text back into values for the API: numbers stay numbers, an empty box is null. */
export function formValues(fields: OsDocField[], text: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = (text[f.field] ?? startValue(f)).trim();
    if (raw === '') out[f.field] = null;
    else if (typeof (f.value_confirmed ?? f.value_read) === 'number' && !Number.isNaN(Number(raw))) out[f.field] = Number(raw);
    else out[f.field] = raw;
  }
  return out;
}
