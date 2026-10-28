// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
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
    expect(completeActions(admission).map((a) => [a.label, a.payload])).toEqual([
      ['Admitted', { choice: 'admitted' }],
      ['Not admitted', { choice: 'rejected' }],
    ]);
    expect(completeActions(item({ inbox_kind: 'choose' }))).toEqual([{ label: 'Confirm', payload: {} }]);
    expect(completeActions(item({}))).toEqual([{ label: 'Mark as done', payload: {} }]);
    const html = renderToStaticMarkup(<InboxList items={[admission]} now={NOW} onComplete={() => {}} />);
    expect(html).toContain('>Admitted<');
    expect(html).toContain('>Not admitted<');
  });
});

// Slice 9 Task 11: the rehearsal walkthroughs' inbox findings. Fictional programmes only.
describe('per-programme items name their programme (walk:S3:admission_card_unnamed, walk:S1:inbox_programme_unnamed)', () => {
  afterEach(() => cleanup());
  const a = item({ id: 7, instance_key: 'admission_result@p1', inbox_kind: 'choose', programme_ref: 'p1',
                   title: "Tell us this programme's admission result", programme_name: 'MSc Example',
                   university: 'Uni Sample' });
  const b = item({ id: 8, instance_key: 'admission_result@p2', inbox_kind: 'choose', programme_ref: 'p2',
                   title: "Tell us this programme's admission result", programme_name: 'MSc Other',
                   university: 'Uni Two' });

  it('shows each programme by name, never its ref', () => {
    const html = renderToStaticMarkup(<InboxList items={[a, b, item({ id: 9, programme_ref: 'p3' })]} now={NOW}
                                                 onComplete={() => {}} names={{ p3: 'MSc Third' }} />);
    expect(html).toContain('MSc Example (Uni Sample)');
    expect(html).toContain('MSc Other (Uni Two)');
    expect(html).toContain('MSc Third');  // no name on the item: the page's names
    expect(html).not.toMatch(/>p[123]</);
  });

  it('"Not admitted" names the programme and is recorded only after a second tap', () => {
    const onComplete = vi.fn();
    render(<InboxList items={[a, b]} now={NOW} onComplete={onComplete} />);
    fireEvent.click(screen.getAllByRole('button', { name: 'Not admitted' })[1]);
    expect(onComplete).not.toHaveBeenCalled();
    const ask = screen.getByRole('alertdialog');
    expect(ask.textContent).toContain('MSc Other (Uni Two)');
    expect(ask.textContent).not.toContain('MSc Example');
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(onComplete).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: 'Not admitted' })[1]);
    fireEvent.click(screen.getByRole('button', { name: /MSc Other \(Uni Two\) did not admit me/ }));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete.mock.calls[0][0].id).toBe(8);
    expect(onComplete.mock.calls[0][1]).toEqual({ choice: 'rejected' });
  });

  it('"Admitted" is recorded at once', () => {
    const onComplete = vi.fn();
    render(<InboxList items={[a]} now={NOW} onComplete={onComplete} />);
    fireEvent.click(screen.getByRole('button', { name: 'Admitted' }));
    expect(onComplete).toHaveBeenCalledWith(a, { choice: 'admitted' });
  });
});

describe('plan updates and provide steps (walk:S1:plan_updated_notice_empty, walk:S1:done_after_upload)', () => {
  it('a plan update says what changed, by step title and programme name, with an OK', () => {
    const notice = item({ instance_key: 'plan_updated@r4', title: 'Your plan was updated', changes: [
      { change: 'removed', instance_key: 'apply@p1', title: 'Submit your application', programme_ref: 'p1',
        programme_name: 'MSc Example' },
      { change: 'changed', instance_key: 'visa_apply', title: 'Apply for your visa', programme_ref: null },
    ] });
    const html = renderToStaticMarkup(<InboxList items={[notice]} now={NOW} onComplete={() => {}} />);
    expect(html).toContain('Removed: Submit your application (MSc Example)');
    expect(html).toContain('Updated: Apply for your visa');
    expect(html).toContain('>OK<');
    expect(html).not.toContain('>Mark as done<');
  });

  it('a provide step says an upload alone does not close it', () => {
    const html = renderToStaticMarkup(
      <InboxList items={[item({ inbox_kind: 'provide', title: 'Upload your school certificates' })]} now={NOW}
                 onComplete={() => {}} />);
    expect(html).toContain('Uploading alone does not close this step');
    expect(html).toContain('>Mark as done<');
    expect(html).not.toContain('>Done<');
  });
});
