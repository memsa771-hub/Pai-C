import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ProgrammeFacts } from './programme-facts';
import { InboxList } from './inbox-list';
import {
  dateFactStatus,
  fillDraft,
  formatFactValue,
  statusLabel,
  type OsFact,
  type OsProgramme,
} from '@/lib/os-programmes';
import type { OsInboxItem } from '@/lib/os-inbox';

function fact(over: Partial<OsFact>): OsFact {
  return {
    field: 'deadline_close', value: { date: '2027-07-15' }, status: 'confirmed',
    source_url: 'https://www.tu-chemnitz.de/apply', quote: 'Apply by 15 July 2027.',
    checked_at: '2026-10-12T08:00:00Z', conflict_note: null, ...over,
  };
}

function programme(over: Partial<OsProgramme>): OsProgramme {
  return {
    ref: 'tu-chemnitz-embedded-systems', name: 'Embedded Systems', university: 'TU Chemnitz', intake_year: 2027,
    facts: [fact({})], ...over,
  };
}

describe('programme fact helpers', () => {
  it('labels confirmed, unconfirmed and stale facts', () => {
    expect(statusLabel('confirmed')).toBe('✓ checked');
    expect(statusLabel('unconfirmed')).toBe('⚠ unconfirmed');
    expect(statusLabel('stale')).toBe('⚠ needs re-check');
  });

  it('formats values of every shape', () => {
    expect(formatFactValue({ date: '2027-07-15', tz: 'Europe/Berlin' })).toBe('15 Jul 2027');
    expect(formatFactValue('uni_assist')).toBe('uni assist');
    expect(formatFactValue({ cefr: 'B2', ielts: 6.5, toefl_ibt: null, moi_accepted: false })).toBe('cefr B2 · ielts 6.5 · moi accepted no');
    expect(formatFactValue([])).toBe('none');
    expect(formatFactValue(['winter', 'summer'])).toBe('winter, summer');
    expect(formatFactValue(0)).toBe('0');
  });

  it('takes the weakest status of a programme date facts', () => {
    const p = programme({ facts: [fact({}), fact({ field: 'deadline_open', status: 'stale' }),
                                  fact({ field: 'application_route', value: 'direct', status: 'unconfirmed' })] });
    expect(dateFactStatus(p)).toBe('stale');  // the route is not a date
    expect(dateFactStatus(programme({}))).toBe('confirmed');
    expect(dateFactStatus(programme({ facts: [] }))).toBeNull();
  });

  it('fills the draft email from the template', () => {
    const p = programme({});
    const draft = fillDraft(undefined, p, fact({ status: 'unconfirmed' }));
    expect(draft).toContain('Embedded Systems at TU Chemnitz');
    expect(draft).toContain('for the 2027 intake');
    expect(draft).toContain('Deadline close: 15 Jul 2027?');
    expect(draft).toContain('"Apply by 15 July 2027." (https://www.tu-chemnitz.de/apply)');
    expect(fillDraft('Hi {programme} / {question}', p, fact({}))).toBe('Hi Embedded Systems / Deadline close: 15 Jul 2027?');
  });
});

describe('ProgrammeFacts', () => {
  const html = renderToStaticMarkup(
    <ProgrammeFacts
      programmes={[programme({
        facts: [
          fact({}),
          fact({ field: 'application_route', value: 'uni_assist', status: 'unconfirmed',
                 conflict_note: 'page shows WS 2026/27', quote: null, source_url: null }),
          fact({ field: 'semester_contribution_eur', value: 322.8, status: 'stale' }),
        ],
      })]}
    />,
  );

  it('shows each value with its status label and source link', () => {
    expect(html).toContain('TU Chemnitz · Embedded Systems');
    expect(html).toContain('>✓ checked<') ;
    expect(html).toContain('>⚠ unconfirmed<');
    expect(html).toContain('>⚠ needs re-check<');
    expect(html).toContain('href="https://www.tu-chemnitz.de/apply"');
    expect(html).toContain('source: tu-chemnitz.de');
    expect(html).toContain('checked 12 Oct 2026');
  });

  it('shows the quote on tap', () => {
    expect(html).toMatch(/<details[^>]*><summary[^>]*>Show the quote<\/summary>[\s\S]*Apply by 15 July 2027\./);
  });

  it('shows the conflict note and the draft email for facts that are not checked', () => {
    expect(html).toContain('page shows WS 2026/27');
    expect(html).toContain('Ask the university');
    expect(html).toContain('Could you please confirm: Application route: uni assist?');
    expect(html.match(/Ask the university/g)?.length).toBe(2);  // the unconfirmed and the stale fact, not the checked one
  });

  it('fits 360 px: no horizontal overflow, long text wraps', () => {
    expect(html).not.toMatch(/overflow-x|whitespace-nowrap|w-\[\d{3,}px\]|min-w-\[/);
    expect(html).toContain('break-words');
    expect(html).toContain('max-w-md');
  });

  it('shows an empty state', () => {
    expect(renderToStaticMarkup(<ProgrammeFacts programmes={[]} />)).toContain('No programmes in your plan yet');
  });
});

describe('InboxList fact labels', () => {
  it('shows the programme fact label and links to the programme facts page', () => {
    const item: OsInboxItem = {
      id: 9, instance_key: 'apply@tu-chemnitz-embedded-systems', title: 'Apply', kind: 'student', inbox_kind: 'act',
      programme_ref: 'tu-chemnitz-embedded-systems', state: 'waiting_student', blocked_reason: null,
      due_at: '2027-07-15T21:59:59Z', due_tz: 'Europe/Berlin', provisional: true, estimated: false, slack_days: 30,
      critical: false, citations: [],
    };
    const html = renderToStaticMarkup(
      <InboxList items={[item]} now={new Date('2027-03-10T09:00:00Z')} onComplete={() => {}}
                 factStatus={{ 'tu-chemnitz-embedded-systems': 'unconfirmed' }} programmesHref="/ws1/os-programmes" />,
    );
    expect(html).toContain('>provisional<');
    expect(html).toContain('>⚠ unconfirmed<');
    expect(html).toContain('href="/ws1/os-programmes#tu-chemnitz-embedded-systems"');
  });
});
