// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { renderToStaticMarkup } from 'react-dom/server';
import { InboxList } from './inbox-list';
import { actionHint, changeLine, completeActions, type OsInboxItem } from '@/lib/os-inbox';
import copy from '@/components/counselor/workspace/copy.json';

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

// Slice 9 Task 11 batch C. Fictional programmes and dates only.
describe('a step waiting for a fact (walk:S1:nothing_to_do_while_blocked, F1)', () => {
  afterEach(() => cleanup());
  const visa = item({ id: 20, instance_key: 'visa_apply', title: 'Apply for the student visa', state: 'blocked',
                      blocked_reason: 'fact_missing:semester_start',
                      waiting_for: "Waiting for your programme's semester start date" });

  it('says what the plan waits for instead of "Nothing to do", with nothing to tap', () => {
    const html = renderToStaticMarkup(<InboxList items={[visa]} now={NOW} onComplete={() => {}} />);
    expect(html).not.toContain('Nothing to do');
    expect(html).toContain('Apply for the student visa');
    expect(html).toContain("Waiting for your programme&#x27;s semester start date");
    expect(html).not.toContain('>Mark as done<');
  });

  it('lists waiting steps after the ones to do, and words a reason the playbook does not', () => {
    const todo = item({ id: 21, title: 'Open a blocked account', due_at: '2027-03-13T22:59:59Z' });
    const other = item({ id: 22, instance_key: 'apply@p1', title: 'Apply', state: 'blocked',
                         blocked_reason: 'fact_missing:deadline_close' });
    const html = renderToStaticMarkup(<InboxList items={[visa, todo, other]} now={NOW} onComplete={() => {}} />);
    expect(html.indexOf('Open a blocked account')).toBeLessThan(html.indexOf('>Waiting<'));
    expect(html.indexOf('>Waiting<')).toBeLessThan(html.indexOf('Apply for the student visa'));
    expect(html).toContain('Waiting for a date we are still checking');
    expect(html.match(/>Mark as done</g)?.length).toBe(1);
  });

  it('shows how a derived date follows from its source', () => {
    const ready = item({ id: 23, title: 'Apply for the student visa', due_at: '2027-08-20T21:59:59Z',
                         citations: [{ source: 'fact:semester_start', url: 'https://uni.example/dates',
                                       note: '6 weeks before your semester starts on 1 October 2027' }] });
    const html = renderToStaticMarkup(<InboxList items={[ready]} now={NOW} onComplete={() => {}} />);
    expect(html).toContain('6 weeks before your semester starts on 1 October 2027');
    expect(html).toContain('source: uni.example');
  });
});

describe('"Not admitted" question focus (batch B review)', () => {
  afterEach(() => cleanup());
  const a = item({ id: 30, instance_key: 'admission_result@p1', inbox_kind: 'choose', programme_ref: 'p1',
                   title: "Tell us this programme's admission result", programme_name: 'MSc Example' });

  it('moves focus into the question, and back to "Not admitted" on Cancel', () => {
    render(<InboxList items={[a]} now={NOW} onComplete={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Not admitted' }));
    expect(screen.getByRole('alertdialog').contains(document.activeElement)).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Not admitted' }));
  });
});

describe('plan change words (batch B review)', () => {
  it('a kept step says only "Kept" (it may be started or kept on purpose)', () => {
    expect(changeLine({ change: 'kept', instance_key: 'k', title: 'Apply', programme_ref: null })).toBe('Kept: Apply');
  });
});

// P1-T8 Task 6: the inbox shows what the plan asks of the student (R-19) and lets them settle two values (R-21).
import type { OsChoice, OsRequest } from '@/lib/os-requests';
import { withRequests } from '@/lib/os-requests';

const choice = (over: Partial<OsChoice>): OsChoice => ({
  ref: 'card-1', key: 'education.matric.marks_obtained', seen: 'tok', choice: 'current', label: 'Saved in PAI', value: 770,
  source: { kind: 'vault', evidence: 'stated', document_ref: null, as_of: null }, ...over,
});
const request = (over: Partial<OsRequest>): OsRequest => ({
  id: 9, task_id: 40, kind: 'provide', need: { kind: 'fact', ref: 'education.matric.marks_obtained', evidence: 'stated' },
  status: 'open', due_at: null, due_tz: null, title: null, how: 'Tell PAI in the chat or on your profile page.',
  ref: null, seen: null, choices: [], allow_new: false, new_label: null, ...over,
});
const which = request({
  id: 10, task_id: 41, kind: 'which_is_right', how: 'Two places say different things. Choose the one that is right, or type the right value.',
  ref: 'card-1', seen: 'tok', allow_new: true, new_label: 'Neither: I will type the right value',
  choices: [choice({}), choice({ choice: 'proposed', label: 'From your document', value: 760,
    source: { kind: 'document', evidence: 'shown', document_ref: 'doc-1', as_of: '2027-02-01T00:00:00Z' } })],
});

describe('requests in the inbox (P1-T8 Task 6)', () => {
  afterEach(() => cleanup());

  // req: R-19
  it('request item shows how and no Mark as done', () => {
    const items = withRequests([item({ id: 40, inbox_kind: 'provide', title: 'Your matric marks' })], [request({})]);
    render(<InboxList items={items} now={NOW} onComplete={() => {}} />);
    expect(screen.getByText('Tell PAI in the chat or on your profile page.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Mark as done' })).toBeNull();
    expect(screen.queryByText(/Uploading alone/)).toBeNull();
    expect(completeActions(items[0])).toEqual([]);
  });

  // req: R-19
  it('an answered request, or none, leaves the item as today', () => {
    const plain = item({ id: 40, inbox_kind: 'provide' });
    expect(withRequests([plain], null)).toEqual([plain]);
    expect(withRequests([plain], [request({ status: 'answered' })])).toEqual([plain]);
    render(<InboxList items={[plain]} now={NOW} onComplete={() => {}} />);
    expect(screen.getByRole('button', { name: 'Mark as done' })).toBeTruthy();
  });

  // req: R-21
  it('which is right shows both values with sources and answers', () => {
    const onAnswer = vi.fn();
    const items = withRequests([item({ id: 41, inbox_kind: 'choose', title: 'Which marks are right?' })], [which]);
    render(<InboxList items={items} now={NOW} onComplete={() => {}} onAnswer={onAnswer} />);
    expect(screen.getByText(which.how)).toBeTruthy();
    const saved = screen.getByRole('button', { name: /Saved in PAI/ });
    const doc = screen.getByRole('button', { name: /From your document/ });
    expect(saved.textContent).toContain('770');
    expect(saved.textContent).toContain('Saved in PAI');
    expect(saved.textContent).toContain('you told PAI');
    expect(doc.textContent).toContain('760');
    expect(doc.textContent).not.toContain('Your document');  // the label already says it: not said twice
    expect(doc.textContent?.match(/From your document/g)).toHaveLength(1);
    expect(doc.textContent).toContain('shown in a document');
    expect(doc.textContent).toContain('1 Feb 2027');
    expect(screen.queryByRole('button', { name: 'Mark as done' })).toBeNull();
    fireEvent.click(doc);
    expect(onAnswer).toHaveBeenCalledWith(which, 'proposed', undefined);
  });

  // req: R-21
  it('typing a new value sends choice new', () => {
    const onAnswer = vi.fn();
    const items = withRequests([item({ id: 41, inbox_kind: 'choose' })], [which]);
    render(<InboxList items={items} now={NOW} onComplete={() => {}} onAnswer={onAnswer} />);
    const field = screen.getByLabelText('Neither: I will type the right value');
    const use = screen.getByRole('button', { name: 'Use this value' }) as HTMLButtonElement;
    expect(use.disabled).toBe(true);
    fireEvent.change(field, { target: { value: '765' } });
    fireEvent.click(use);
    expect(onAnswer).toHaveBeenCalledWith(which, 'new', 765);
  });

  // req: R-21
  it('a finding of documents offers no field to type in', () => {
    const finding = { ...which, allow_new: false, new_label: null,
      choices: which.choices.map((c, i) => ({ ...c, choice: `doc:${i + 1}` })) };
    render(<InboxList items={withRequests([item({ id: 41 })], [finding])} now={NOW} onComplete={() => {}} onAnswer={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Use this value' })).toBeNull();
    expect(screen.getAllByRole('button').map((b) => b.textContent).join()).toContain('760');
  });

  // req: R-18
  it('an impossible value asks only for the right value', () => {
    const impossible = request({ id: 11, task_id: 42, kind: 'which_is_right', how: 'This value is higher than its total. Type the right value.',
      ref: 'impossible:a:b', seen: 'z', allow_new: true, new_label: 'Neither: I will type the right value', choices: [] });
    render(<InboxList items={withRequests([item({ id: 42 })], [impossible])} now={NOW} onComplete={() => {}} onAnswer={() => {}} />);
    expect(screen.getByText(impossible.how)).toBeTruthy();
    expect(screen.getByLabelText('Neither: I will type the right value')).toBeTruthy();
  });

  // req: R-19
  it('a request step has no Mark as done also when the requests could not be loaded', () => {
    const ask = item({ id: 50, instance_key: 'provide@fact:education.matric.marks_obtained:stated', inbox_kind: 'provide' });
    render(<InboxList items={withRequests([ask], null)} now={NOW} onComplete={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Mark as done' })).toBeNull();
    expect(screen.queryByText(/Uploading alone/)).toBeNull();
    expect(screen.getByText(copy.connect.requests.pending)).toBeTruthy();
    expect(completeActions(ask)).toEqual([]);
    expect(actionHint(ask)).toBe(copy.connect.requests.pending);
  });

  // req: R-21
  it('a value the student told PAI is not called saved or a document', () => {
    const said = request({ ...which, id: 12, task_id: 43, choices: [choice({}), choice({ choice: 'proposed', label: 'What you told PAI', value: 760,
      source: { kind: 'said', evidence: 'stated', document_ref: null, as_of: null } })] });
    render(<InboxList items={withRequests([item({ id: 43 })], [said])} now={NOW} onComplete={() => {}} onAnswer={() => {}} />);
    const b = screen.getByRole('button', { name: /760/ });
    expect(b.textContent).toContain('What you told PAI');
    expect(b.textContent).not.toContain('Saved in PAI');
    expect(b.textContent?.match(/What you told PAI/g)).toHaveLength(1);  // the kind word repeats the label: left out
  });

  // req: R-21
  it('only plain decimal digits are sent as a number, and a text value gets a text keyboard', () => {
    const onAnswer = vi.fn();
    render(<InboxList items={withRequests([item({ id: 41 })], [which])} now={NOW} onComplete={() => {}} onAnswer={onAnswer} />);
    const field = screen.getByLabelText('Neither: I will type the right value') as HTMLInputElement;
    const use = screen.getByRole('button', { name: 'Use this value' }) as HTMLButtonElement;
    expect(field.getAttribute('inputmode')).toBe('decimal');
    for (const bad of ['0x2FA', '1e3', '7 70', '--5']) {
      fireEvent.change(field, { target: { value: bad } });
      expect(use.disabled).toBe(true);
    }
    fireEvent.change(field, { target: { value: '76.5' } });
    fireEvent.click(use);
    expect(onAnswer).toHaveBeenCalledWith(which, 'new', 76.5);
    cleanup();
    const text = request({ ...which, choices: which.choices.map((c) => ({ ...c, value: 'Grade B' })) });
    render(<InboxList items={withRequests([item({ id: 41 })], [text])} now={NOW} onComplete={() => {}} onAnswer={onAnswer} />);
    expect(screen.getByLabelText('Neither: I will type the right value').getAttribute('inputmode')).toBe('text');
  });
});
