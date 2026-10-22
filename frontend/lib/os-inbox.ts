/**
 * PAI OS student inbox: types and pure helpers (grouping, due labels).
 * Data comes from GET /v1/os/inbox (backend/app/os/api). Kept free of React so it is easy to test.
 */

export type InboxKind = 'provide' | 'approve' | 'act' | 'choose';

export interface OsCitation {
  source: string;
  url: string;
}

export interface OsInboxItem {
  id: number;
  instance_key: string;
  title: string;
  kind: string;
  inbox_kind: InboxKind | null;
  programme_ref: string | null;
  state: string;
  blocked_reason: string | null;
  due_at: string | null;
  due_tz: string;
  provisional: boolean;
  estimated: boolean;
  slack_days: number | null;
  critical: boolean;
  citations: OsCitation[];
}

export type InboxGroup = 'overdue' | 'this_week' | 'later';

export const GROUP_ORDER: InboxGroup[] = ['overdue', 'this_week', 'later'];

export const GROUP_TITLES: Record<InboxGroup, string> = {
  overdue: 'Overdue',
  this_week: 'This week',
  later: 'Later',
};

export const KIND_LABELS: Record<InboxKind, string> = {
  provide: 'Provide',
  approve: 'Approve',
  act: 'Act',
  choose: 'Choose',
};

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export function groupOf(item: OsInboxItem, now: Date): InboxGroup {
  if (!item.due_at) return 'later';
  const due = new Date(item.due_at).getTime();
  if (due < now.getTime()) return 'overdue';
  if (due - now.getTime() <= WEEK_MS) return 'this_week';
  return 'later';
}

/** Groups in display order; empty groups are left out. Items keep the API's due-date order. */
export function groupItems(items: OsInboxItem[], now: Date): { group: InboxGroup; items: OsInboxItem[] }[] {
  return GROUP_ORDER.map((group) => ({ group, items: items.filter((i) => groupOf(i, now) === group) })).filter(
    (g) => g.items.length > 0,
  );
}

/** "Europe/Berlin" -> "Berlin": the institution's timezone shown next to every due date (invariant 13). */
export function tzLabel(tz: string): string {
  const city = tz.split('/').pop() ?? tz;
  return city.replace(/_/g, ' ');
}

/** "due 15 Jul 2027, 23:59 (Berlin)" in the institution's timezone, not the student's. */
export function formatDue(item: OsInboxItem): string | null {
  if (!item.due_at) return null;
  const when = new Intl.DateTimeFormat('en-GB', {
    timeZone: item.due_tz,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(item.due_at));
  return `due ${when} (${tzLabel(item.due_tz)})`;
}

/** Short labels that tell the student how firm a date is (parent spec success criterion 2). */
export function dateLabels(item: OsInboxItem): string[] {
  const labels: string[] = [];
  if (item.provisional) labels.push('provisional');
  if (item.estimated) labels.push('estimated');
  return labels;
}

export function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\d?\./, '');
  } catch {
    return url;
  }
}

const ADMISSION_PREFIX = 'admission_result@'; // the plan's per-programme admission step (Slice 6b S6b-D8)

/** The buttons an item offers and what each sends: an admission result says admitted or not (the visa page
 * pre-selects the admitted programme); other choices confirm; the rest are done. */
export function completeActions(item: OsInboxItem): { label: string; payload: Record<string, unknown> }[] {
  if (item.instance_key.startsWith(ADMISSION_PREFIX)) {
    return [{ label: 'Admitted', payload: { choice: 'admitted' } },
            { label: 'Not admitted', payload: { choice: 'rejected' } }];
  }
  return [{ label: item.inbox_kind === 'choose' ? 'Confirm' : 'Done', payload: {} }];
}
