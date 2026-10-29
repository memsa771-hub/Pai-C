/**
 * PAI OS student inbox: types and pure helpers (grouping, due labels).
 * Data comes from GET /v1/os/inbox (backend/app/os/api). Kept free of React so it is easy to test.
 */

export type InboxKind = 'provide' | 'approve' | 'act' | 'choose';

export interface OsCitation {
  source: string;
  url: string;
  /** A derived date's plain explanation, e.g. "6 weeks before your semester starts on 1 October 2027" (Task 11). */
  note?: string;
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
  /** The programme's name and university (Slice 9 Task 11); null when the programme store has no name. */
  programme_name?: string | null;
  university?: string | null;
  /** A "Your plan was updated" item: the student's steps it added, removed, changed or kept. */
  changes?: OsPlanChange[];
  /** A step blocked on a fact nobody has given yet (state "blocked"): what it waits for, in the playbook's words. */
  waiting_for?: string | null;
}

export interface OsPlanChange {
  change: 'added' | 'removed' | 'changed' | 'kept';
  instance_key: string;
  title: string;
  programme_ref: string | null;
  programme_name?: string | null;
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
const NOTICE_PREFIX = 'plan_updated@'; // "Your plan was updated" (the kernel's notice of a revision)

/** The programme an item is for, by name: "MSc Example (Uni Sample)". Never the internal ref: null when no name is
 * known (Slice 9 Task 11). `names` is the page's ref -> name map, used when the item has no name of its own. */
export function programmeName(item: OsInboxItem, names: Record<string, string> = {}): string | null {
  if (!item.programme_ref) return null;
  const name = item.programme_name ?? names[item.programme_ref] ?? null;
  if (!name) return null;
  return item.university && item.programme_name ? `${name} (${item.university})` : name;
}

export function isNotice(item: OsInboxItem): boolean {
  return item.instance_key.startsWith(NOTICE_PREFIX);
}

const CHANGE_WORDS: Record<OsPlanChange['change'], string> = {
  added: 'New step',
  removed: 'Removed',
  changed: 'Updated',
  kept: 'Kept',
};

/** One line of a plan update: 'Removed: Apply (MSc Example)'. */
export function changeLine(c: OsPlanChange, names: Record<string, string> = {}): string {
  const prog = c.programme_name ?? (c.programme_ref ? names[c.programme_ref] : undefined);
  return `${CHANGE_WORDS[c.change] ?? c.change}: ${c.title}${prog ? ` (${prog})` : ''}`;
}

export interface CompleteAction {
  label: string;
  payload: Record<string, unknown>;
  /** Asked before the answer is sent: the button only opens this question (Slice 9 Task 11). */
  confirm?: { question: string; yes: string };
}

/** The buttons an item offers and what each sends: an admission result says admitted or not (the visa page
 * pre-selects the admitted programme); "Not admitted" names the programme and asks first, since it starts removing
 * that programme. Other choices confirm; a plan update is acknowledged; the rest are marked done. */
export function completeActions(item: OsInboxItem, names: Record<string, string> = {}): CompleteAction[] {
  if (item.instance_key.startsWith(ADMISSION_PREFIX)) {
    const name = programmeName(item, names) ?? 'this programme';
    return [{ label: 'Admitted', payload: { choice: 'admitted' } },
            { label: 'Not admitted', payload: { choice: 'rejected' },
              confirm: { question: `Did ${name} say no? We will then suggest removing ${name} from your plan.`,
                         yes: `Yes, ${name} did not admit me` } }];
  }
  if (isNotice(item)) return [{ label: 'OK', payload: {} }];
  if (item.inbox_kind === 'choose') return [{ label: 'Confirm', payload: {} }];
  return [{ label: 'Mark as done', payload: {} }];
}

/** What a step's button means, when it is not plain: a "provide" step is not closed by an upload alone. */
export function actionHint(item: OsInboxItem): string | null {
  if (item.inbox_kind === 'provide') return 'Uploading alone does not close this step: tap Mark as done when it is all done.';
  return null;
}

/** A step listed only to say what the plan waits for (Slice 9 Task 11, walk:S1:nothing_to_do_while_blocked): nothing
 * can be done on it. */
export function isWaiting(item: OsInboxItem): boolean {
  return item.state === 'blocked';
}

/** What a waiting step waits for: the playbook's words, else a plain general line. */
export function waitingText(item: OsInboxItem): string {
  return item.waiting_for ?? 'Waiting for a date we are still checking';
}

/** How a derived date follows from its source (the first citation with a note), e.g. "6 weeks before your semester
 * starts on 1 October 2027"; null when the date is not derived. */
export function dueNote(item: OsInboxItem): string | null {
  return item.citations.find((c) => c.note)?.note ?? null;
}
