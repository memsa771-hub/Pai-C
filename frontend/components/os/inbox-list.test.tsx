import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { InboxList } from './inbox-list';
import { completeActions, type OsInboxItem } from '@/lib/os-inbox';

const NOW = new Date('2027-03-10T09:00:00Z');

function item(over: Partial<OsInboxItem>): OsInboxItem {
  return {
    id: 1, instance_key: 'k', title: 'T', kind: 'student', inbox_kind: 'act', programme_ref: null,
    state: 'waiting_student', blocked_reason: null, due_at: null, due_tz: 'Europe/Berlin', provisional: false,
    estimated: false, slack_days: null, critical: false, citations: [], ...over,
  };
}

describe('InboxList', () => {
  it('groups by due date and shows labels and sources', () => {
    const html = renderToStaticMarkup(
      <InboxList
        now={NOW}
        onComplete={() => {}}
        items={[
          item({ id: 1, inbox_kind: 'provide', title: 'HEC e-Attestation', due_at: '2027-03-01T22:59:59Z',
                 citations: [{ source: 'S8', url: 'https://www.hec.gov.pk/english/x' }] }),
          item({ id: 2, title: 'Book an IELTS test', due_at: '2027-03-13T22:59:59Z', provisional: true, estimated: true }),
          item({ id: 3, inbox_kind: 'choose', title: 'Confirm your programmes' }),
        ]}
      />,
    );
    const order = ['Overdue', 'This week', 'Later'].map((h) => html.indexOf(`>${h}<`));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(html).toContain('href="https://www.hec.gov.pk/english/x"');
    expect(html).toContain('source: hec.gov.pk');
    expect(html).toContain('(Berlin)');
    expect(html).toContain('>provisional<');
    expect(html).toContain('>estimated<');
    expect(html).toContain('>Confirm<');
  });

  it('shows an empty state', () => {
    expect(renderToStaticMarkup(<InboxList items={[]} now={NOW} onComplete={() => {}} />)).toContain('Nothing to do');
  });
});

describe('admission result (Slice 6b final review I2)', () => {
  it('asks admitted or not, and sends the choice the visa page pre-selects from', () => {
    const admission = item({ instance_key: 'admission_result@p1', inbox_kind: 'choose', programme_ref: 'p1' });
    expect(completeActions(admission)).toEqual([
      { label: 'Admitted', payload: { choice: 'admitted' } },
      { label: 'Not admitted', payload: { choice: 'rejected' } },
    ]);
    expect(completeActions(item({ inbox_kind: 'choose' }))).toEqual([{ label: 'Confirm', payload: {} }]);
    expect(completeActions(item({}))).toEqual([{ label: 'Done', payload: {} }]);
    const html = renderToStaticMarkup(<InboxList items={[admission]} now={NOW} onComplete={() => {}} />);
    expect(html).toContain('>Admitted<');
    expect(html).toContain('>Not admitted<');
  });
});
