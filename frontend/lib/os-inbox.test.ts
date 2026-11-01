import { describe, expect, it } from 'vitest';
import {
  collapseNotices, completeActions, dateLabels, formatDue, groupItems, reviewPage, sourceHost, tzLabel, NOTICE_PREFIX,
  type OsInboxItem,
} from './os-inbox';

const NOW = new Date('2027-03-10T09:00:00Z');

function item(over: Partial<OsInboxItem>): OsInboxItem {
  return {
    id: 1, instance_key: 'k', title: 'T', kind: 'student', inbox_kind: 'act', programme_ref: null,
    state: 'waiting_student', blocked_reason: null, due_at: null, due_tz: 'Europe/Berlin', provisional: false,
    estimated: false, slack_days: null, critical: false, citations: [], ...over,
  };
}

describe('groupItems', () => {
  it('groups by due date in Overdue / This week / Later order and drops empty groups', () => {
    const overdue = item({ id: 1, due_at: '2027-03-01T22:59:59Z' });
    const soon = item({ id: 2, due_at: '2027-03-13T22:59:59Z', provisional: true });
    const undated = item({ id: 3, due_at: null });
    const groups = groupItems([overdue, soon, undated], NOW);
    expect(groups.map((g) => g.group)).toEqual(['overdue', 'this_week', 'later']);
    expect(groups.map((g) => g.items.map((i) => i.id))).toEqual([[1], [2], [3]]);
    expect(groupItems([undated], NOW).map((g) => g.group)).toEqual(['later']);
  });
});

describe('due labels', () => {
  it('shows the due time in the institution timezone with its city', () => {
    const due = formatDue(item({ due_at: '2027-07-15T21:59:59Z', due_tz: 'Europe/Berlin' }));
    expect(due).toBe('due 15 Jul 2027, 23:59 (Berlin)');
    expect(formatDue(item({ due_at: null }))).toBeNull();
    expect(tzLabel('America/New_York')).toBe('New York');
  });

  it('labels provisional and estimated dates', () => {
    expect(dateLabels(item({ provisional: true, estimated: true }))).toEqual(['provisional', 'estimated']);
    expect(dateLabels(item({}))).toEqual([]);
  });

  it('shows a short source host for citation links', () => {
    expect(sourceHost('https://www.hec.gov.pk/english/x')).toBe('hec.gov.pk');
    expect(sourceHost('https://www2.daad.de/a')).toBe('daad.de');
    expect(sourceHost('not a url')).toBe('not a url');
  });
});

describe('review steps', () => {
  it('link to their pack or visa file instead of offering Mark as done', () => {
    const pack = item({ instance_key: 'review_pack@ovgu-eeit', inbox_kind: 'approve' });
    const visa = item({ instance_key: 'review_visa_file', inbox_kind: 'approve' });
    expect(reviewPage(pack)).toEqual({ page: 'os-pack', label: 'Open pack' });
    expect(reviewPage(visa)).toEqual({ page: 'os-visa', label: 'Open visa file' });
    expect(completeActions(pack)).toEqual([]);
    expect(completeActions(item({ instance_key: 'visa_apply' })).map((a) => a.label)).toEqual(['Mark as done']);
  });
});

describe('collapseNotices', () => {
  it('shows a plan update once when copies say the same, and keeps the copies for its OK', () => {
    const change = { change: 'changed' as const, instance_key: 'visa_apply', title: 'Apply', programme_ref: null };
    const a = item({ id: 1, instance_key: `${NOTICE_PREFIX}1`, title: 'Your plan was updated', changes: [change] });
    const b = item({ id: 2, instance_key: `${NOTICE_PREFIX}2`, title: 'Your plan was updated', changes: [change] });
    const other = item({ id: 3, instance_key: `${NOTICE_PREFIX}3`, title: 'Your plan was updated',
                         changes: [{ ...change, change: 'added' as const }] });
    const step = item({ id: 4 });
    const { items, copies } = collapseNotices([a, b, other, step]);
    expect(items.map((i) => i.id)).toEqual([1, 3, 4]);
    expect(copies.get(1)).toEqual([2]);
  });
});
