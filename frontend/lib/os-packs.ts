/**
 * PAI OS application packs: types and pure helpers. Data comes from GET /v1/os/packs (backend/app/os/api/packs.py,
 * Slice 6a spec §4-5). Kept free of React. Nothing here knows a route or a portal: every label, step and fee comes
 * from the API.
 */

export type PackStatus = 'building' | 'ready' | 'incomplete' | 'approved' | 'failed';

export interface OsPackItem {
  key: string;
  label: string;
  kind: 'document' | 'statement' | 'entered' | 'manual';
  state: 'ready' | 'missing' | 'needs_action' | 'manual';
  ticked: boolean;
  reasons: string[];
  source: 'research' | 'default' | 'student';
  document_id: number | null;
  tickable: boolean;
  after_approval?: boolean; // a step after approving (Slice 9 Task 11): it never blocks approval
}

/** A step the student takes after approving, e.g. paying the fee (Slice 9 Task 11). Its tick is not part of what is
 * approved: ticking it never changes the approved version. */
export interface OsAfterItem {
  key: string;
  label: string;
  note: string | null;
  ticked: boolean;
}

export interface OsSheetRow {
  section: string;
  key: string;
  label: string;
  value: string | null;
  source: 'document' | 'entered' | null;
  document_id: number | null;
  gap: boolean;
  hint: string;
  entered: boolean;
}

export interface OsInstructionStep {
  n: number;
  text: string;
  source_url: string | null;
  unconfirmed: string[];
}

export interface OsFee {
  label: string;
  value: string | null;
  status: string;
  source_url: string | null;
}

export interface OsPackFile {
  key: string;
  sha256: string;
  filename: string;
  size: number;
  pages: number;
}

export interface OsPack {
  programme_ref: string;
  name: string | null;
  university: string | null;
  status: PackStatus;
  version: number | null;
  approved: boolean;
  manifest_sha256: string | null;
  route_value: string | null;
  instructions: OsInstructionStep[];
  fees: OsFee[];
  checklist: OsPackItem[];
  data_sheet: OsSheetRow[];
  files: OsPackFile[];
  after_approval?: OsAfterItem[]; // older APIs send none
}

export interface OsPacks {
  route: string;
  programmes: OsPack[];
}

export const DATA_SHEET_KEY = 'data_sheet';

/** Items still to do: not ready, or a tick-settled item not ticked yet. */
export function todoCount(p: OsPack): number {
  return beforeApproval(p).filter((i) => (i.state === 'manual' ? !i.ticked : i.state !== 'ready')).length;
}

/** The checklist items the approval covers: never the steps after approving (Slice 9 Task 11). */
function beforeApproval(p: OsPack): OsPackItem[] {
  return p.checklist.filter((i) => !i.after_approval);
}

export function packStatusLabel(p: OsPack): string {
  switch (p.status) {
    case 'building': return 'being prepared…';
    case 'ready': return 'ready to approve';
    case 'approved': return 'approved ✓';
    case 'failed': return 'could not be prepared';
    default: return `${todoCount(p)} to do`;
  }
}

/** What is left before the pack (or visa file) can be approved, in the student's words (Slice 9 Task 11): an item
 * the student ticks says so. The server's rule: every item is ready, and every manual item is ticked; a step after
 * approving (paying the fee) never counts. */
export function approveBlockers(p: OsPack): string[] {
  return beforeApproval(p).filter((i) => (i.state === 'manual' ? !i.ticked : i.state !== 'ready'))
    .map((i) => (i.tickable ? `${i.label} (tick it once you have done it)` : i.label));
}

export function canApprove(p: OsPack): boolean {
  return p.status === 'ready' && !p.approved && p.manifest_sha256 !== null;
}

export function programmeTitle(p: OsPack): string {
  return [p.university, p.name ?? p.programme_ref].filter(Boolean).join(' · ');
}

export function fileFor(p: OsPack, key: string): OsPackFile | undefined {
  return p.files.find((f) => f.key === key);
}

export function feeValue(f: OsFee): string {
  return f.value === null ? 'not known yet' : `${f.value} (${f.status})`;
}
