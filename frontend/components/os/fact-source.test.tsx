import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactElement } from 'react';
import copy from '@/components/counselor/workspace/copy.json';
import { factLevel, stepLevel, checkedOn, sourceLevel, type MyPlan } from '@/lib/os-my-plan';
import type { OsInboxItem } from '@/lib/os-inbox';
import type { OsPack } from '@/lib/os-packs';
import type { OsCard } from '@/lib/os-self-serve';
import { FactSource } from './fact-source';
import { MyPlanContext } from './my-plan-context';
import { ProgrammeFacts } from './programme-facts';
import { InboxList } from './inbox-list';
import { PackView } from './pack';
import { VisaFunds } from './visa-funds';
import { EligibilityCard } from './eligibility-card';
import { StepMeta } from '@/components/counselor/workspace/roadmap-steps';

const L = copy.connect.myPlan.levels;
const noop = () => {};
const PLAN: MyPlan = {
  state: 'active', source: 'self_serve', plan_id: 1, route_key: 'r', abroad: true, pages: [],
  sources: {
    'https://a.example/x': { checked_at: '2026-10-17', confirmed: true },
    'https://b.example/y': { checked_at: '2026-10-12', confirmed: false },
  },
};
const on = (el: ReactElement, plan: MyPlan = PLAN) =>
  renderToStaticMarkup(<MyPlanContext.Provider value={{ on: true, plan, refresh: noop }}>{el}</MyPlanContext.Provider>);
const off = (el: ReactElement) => renderToStaticMarkup(el);

const fact = (over = {}) => ({
  field: 'deadline_close', value: { date: '2027-07-15' }, status: 'confirmed' as const, source_url: 'https://a.example/x',
  quote: null, checked_at: '2026-10-12T08:00:00Z', conflict_note: null, ...over,
});
const prog = (facts: ReturnType<typeof fact>[]) => [{ ref: 'p1', name: 'MSc Example', university: 'Uni Sample', intake_year: 2027, facts }];
const item = (over: Partial<OsInboxItem> = {}): OsInboxItem => ({
  id: 1, instance_key: 'k', title: 'Apply', kind: 'student', inbox_kind: 'act', programme_ref: 'p1', state: 'ready',
  blocked_reason: null, due_at: '2027-03-12T18:59:59Z', due_tz: 'UTC', provisional: false, estimated: false, slack_days: null,
  critical: false, citations: [{ source: 'S1', url: 'https://a.example/x', note: null }], ...over,
});
const pack = (over: Partial<OsPack> = {}): OsPack => ({
  programme_ref: 'p1', name: 'MSc Example', university: 'Uni Sample', status: 'ready', version: 1, approved: false,
  manifest_sha256: 'a'.repeat(64), route_value: 'x',
  instructions: [
    { n: 1, text: 'Create an account.', source_url: 'https://a.example/x', unconfirmed: [] },
    { n: 2, text: 'Apply early.', source_url: 'https://b.example/y', unconfirmed: ['deadline_close'] },
  ],
  fees: [{ label: 'Handling fee', value: '75', status: 'estimate', source_url: 'https://a.example/x' }],
  checklist: [], after_approval: [], data_sheet: [], files: [], ...over,
} as OsPack);
const packView = (p: OsPack) => (
  <PackView pack={p} busy={false} onTick={noop} onAdd={noop} onApprove={noop} onDownload={noop} onRebuild={noop} onDetails={noop} />
);
const funds = (over = {}) => ({
  required: 11904, base: 11904, months: 12, reduction: 0, currency_label: 'XYZ', status: 'unconfirmed', quote: null,
  url: 'https://a.example/x', ...over,
});

describe('levels and dates (R-54)', () => {
  // req: R-54
  it('maps a status to a level and never to verified', () => {
    expect(factLevel('confirmed')).toBe('confirmed');
    for (const s of ['unconfirmed', 'stale', 'missing', 'weird', null, undefined]) expect(factLevel(s)).toBe('not_confirmed');
    expect(factLevel('estimate')).toBe('estimated');
    expect(stepLevel({ estimated: true, provisional: true })).toBe('estimated');
    expect(stepLevel({ provisional: true })).toBe('not_confirmed');
    expect(stepLevel({})).toBe('confirmed');
    expect(checkedOn(PLAN, 'https://a.example/x')).toBe('2026-10-17');
    expect(checkedOn(PLAN, 'https://none.example')).toBeNull();
    expect(checkedOn(null, 'https://a.example/x')).toBeNull();
  });

  it('shows nothing without My plan', () => {
    expect(off(<FactSource level="confirmed" url="https://a.example/x" />)).toBe('');
  });

  it('confirmed fact shows Confirmed, date and source', () => {
    const html = on(<FactSource level="confirmed" url="https://a.example/x" />);
    expect(html).toContain(L.confirmed);
    expect(html).toContain('Checked Oct 17, 2026');
    expect(html).toContain('href="https://a.example/x"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  it('fact with an unrecorded date says Date checked not recorded', () => {
    const html = on(<FactSource level="not_confirmed" url="https://zzz.example/q" />);
    expect(html).toContain(copy.connect.myPlan.checkedUnknown);
    expect(html).not.toContain('Checked ');
  });

  it('no source or an unknown source is never Confirmed (absent is not confirmed)', () => {
    expect(sourceLevel(PLAN, null, 'confirmed')).toBe('not_confirmed');
    expect(sourceLevel(PLAN, '', 'confirmed')).toBe('not_confirmed');
    expect(sourceLevel(PLAN, 'https://zzz.example/q', 'confirmed')).toBe('not_confirmed');
    expect(sourceLevel(PLAN, 'https://a.example/x', 'confirmed')).toBe('confirmed');
    expect(sourceLevel(PLAN, null, 'estimated')).toBe('estimated');
    const html = on(<FactSource level="confirmed" url="https://zzz.example/q" />);
    expect(html).not.toContain(`>${L.confirmed}<`);
    expect(html).toContain(L.not_confirmed);
  });

  it('pack steps and fees without a source are not Confirmed; a firm inbox date without a citation is not Confirmed', () => {
    const p = pack({ instructions: [{ n: 1, text: 'Do it.', source_url: null, unconfirmed: [] }], fees: [] });
    expect(on(packView(p))).not.toContain(`>${L.confirmed}<`);
    const html = on(<InboxList items={[item({ citations: [] })]} now={new Date('2026-11-06T00:00:00Z')} onComplete={noop} />);
    expect(html).toContain(L.not_confirmed);
    expect(html).not.toContain(`>${L.confirmed}<`);
  });

  it('the source link names its host', () => {
    expect(on(<FactSource level="confirmed" url="https://a.example/x" />)).toContain('aria-label="Source: a.example"');
  });

  it('a source the endpoint marks not confirmed is never shown as confirmed', () => {
    const html = on(<FactSource level="confirmed" url="https://b.example/y" />);
    expect(html).toContain(L.not_confirmed);
    expect(html).not.toContain(`>${L.confirmed}<`);
  });
});

describe('surfaces with My plan on (R-54)', () => {
  // req: R-54
  it('unconfirmed programme fact shows Not confirmed, its checked date and source', () => {
    const html = on(<ProgrammeFacts programmes={prog([fact({ status: 'unconfirmed', source_url: 'https://zzz.example/q' })])} />);
    expect(html).toContain(L.not_confirmed);
    expect(html).toContain('Checked Oct 12, 2026');  // the fact's own date: the endpoint has none for this url
    expect(html).toContain('href="https://zzz.example/q"');
  });

  it('confirmed programme fact shows Confirmed, date and source', () => {
    const html = on(<ProgrammeFacts programmes={prog([fact()])} />);
    expect(html).toContain(L.confirmed);
    expect(html).toContain('Checked Oct 17, 2026');
  });

  it('estimated inbox date shows Estimated with the playbook source date', () => {
    const html = on(<InboxList items={[item({ estimated: true })]} now={new Date('2026-11-06T00:00:00Z')} onComplete={noop} />);
    expect(html).toContain(L.estimated);
    expect(html).toContain('Checked Oct 17, 2026');
    expect(html).toContain('href="https://a.example/x"');
  });

  it('an inbox date is held down by a weaker programme fact', () => {
    const html = on(<InboxList items={[item()]} now={new Date('2026-11-06T00:00:00Z')} onComplete={noop}
                               factStatus={{ p1: 'unconfirmed' }} />);
    expect(html).toContain(L.not_confirmed);
  });

  it('pack fee estimate shows Estimated; unconfirmed instruction step shows Not confirmed', () => {
    const html = on(packView(pack()));
    expect(html).toContain(L.estimated);
    expect(html).toContain(L.not_confirmed);
    expect(html).toContain(L.confirmed);  // step 1
    expect(html).toContain('Checked Oct 12, 2026');
  });

  it('visa funds show level, date and source', () => {
    const html = on(<VisaFunds funds={funds()} busy={false} onReduction={noop} />);
    expect(html).toContain(L.not_confirmed);
    expect(html).toContain('Checked Oct 17, 2026');
    expect(html).toContain('href="https://a.example/x"');
  });

  it('eligibility source shows level and date', () => {
    const card: OsCard = { programme_ref: 'p1', verdict: 'likely_meets', lines: [{
      check: 'grade', status: 'likely_meets', have: 1, need: 1, provisional: false, needs: [], reason: null,
      sources: [{ field: 'min_grade', url: 'https://a.example/x', status: 'confirmed' }] }] };
    const html = on(<EligibilityCard card={card} />);
    expect(html).toContain(L.confirmed);
    expect(html).toContain('Checked Oct 17, 2026');
  });

  it('nothing shows Verified in P1 fixtures', () => {
    const all = on(<>
      <ProgrammeFacts programmes={prog([fact(), fact({ status: 'stale', field: 'fee' })])} />
      <InboxList items={[item(), item({ id: 2, provisional: true })]} now={new Date('2026-11-06T00:00:00Z')} onComplete={noop} />
      {packView(pack())}
      <VisaFunds funds={funds({ status: 'confirmed' })} busy={false} onReduction={noop} />
    </>);
    expect(all.toLowerCase()).not.toContain('verified');
  });
});

describe('flags off: every surface renders as today', () => {
  // req: R-54
  it('facts render exactly as today without My plan', () => {
    const off2 = (el: ReactElement) => renderToStaticMarkup(
      <MyPlanContext.Provider value={{ on: false, plan: PLAN, refresh: noop }}>{el}</MyPlanContext.Provider>);
    const els: ReactElement[] = [
      <ProgrammeFacts key="a" programmes={prog([fact(), fact({ status: 'stale', field: 'fee' })])} />,
      <InboxList key="b" items={[item({ estimated: true })]} now={new Date('2026-11-06T00:00:00Z')} onComplete={noop}
                 factStatus={{ p1: 'unconfirmed' }} />,
      packView(pack()),
      <VisaFunds key="c" funds={funds()} busy={false} onReduction={noop} />,
      <EligibilityCard key="d" card={{ programme_ref: 'p1', verdict: 'likely_meets', lines: [{
        check: 'grade', status: 'likely_meets', have: 1, need: 1, provisional: false, needs: [], reason: null,
        sources: [{ field: 'f', url: 'https://a.example/x', status: 'confirmed' }] }] }} />,
      <StepMeta key="e" step={{ key: 's', kind: 'os', status: 'half', due_at: '2027-03-12T18:59:59Z', due_tz: 'UTC', estimated: true } as never} />,
    ];
    for (const el of els) {
      expect(off2(el)).toBe(off(el));
      expect(off(el)).not.toContain('data-fact-source');
    }
  });
});
