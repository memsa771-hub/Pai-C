// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SidebarProvider } from '@/components/ui/sidebar';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import copy from '@/components/counselor/workspace/copy.json';
import { myPlanEmpty, myPlanGermany, myPlanPkBs } from '../../tests/fixtures/counselor';
import { MyPlanProvider } from './my-plan-context';
import { OsNavGroup } from './os-nav-group';
import { OsHeader } from './os-header';
import { OsPlanCard } from './plan-card';
import { OsVaultStrip } from './vault-strip';
import { NotInPlan } from './not-in-plan';
import { CommandMenu } from '@/components/counselor/workspace/shell-parts';
import { pageNoun, pageTitle } from '@/lib/os-my-plan';

const config = vi.hoisted(() => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false }));
vi.mock('@/lib/config', () => ({
  get OS_UI_ENABLED() { return config.OS_UI_ENABLED; },
  get OS_REHEARSAL_UI() { return config.OS_REHEARSAL_UI; },
  OS_FROM_STAGE: 'H',
}));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ workspaceApi: {
  getMyPlan: vi.fn(), getOsInbox: vi.fn(), getAdoption: vi.fn(), getOsDocuments: vi.fn() } }));

beforeAll(() => {
  window.matchMedia ??= ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  window.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(() => { cleanup(); vi.clearAllMocks(); config.OS_UI_ENABLED = true; config.OS_REHEARSAL_UI = false; });

const ITEM = { id: 1, instance_key: 'k', title: 'Collect transcripts', kind: 'student', inbox_kind: 'act', programme_ref: null,
  state: 'ready', blocked_reason: null, due_at: null, due_tz: 'UTC', provisional: false, estimated: false,
  slack_days: null, critical: false, citations: [] };
const DOCS = { documents: [{ id: 1, doc_type: 'passport', status: 'confirmed' }], doc_types: [{ key: 'passport', label: 'Passport' }] };

function plan(answer: unknown) {
  if (answer instanceof Error) vi.mocked(workspaceApi.getMyPlan).mockRejectedValue(answer);
  else vi.mocked(workspaceApi.getMyPlan).mockResolvedValue(answer as never);
  vi.mocked(workspaceApi.getOsInbox).mockResolvedValue([ITEM] as never);
  vi.mocked(workspaceApi.getAdoption).mockResolvedValue({ offer: false } as never);
  vi.mocked(workspaceApi.getOsDocuments).mockResolvedValue(DOCS as never);
}
const wrap = (ui: React.ReactNode, provider = true) => render(
  <I18nProvider><SidebarProvider>{provider ? <MyPlanProvider>{ui}</MyPlanProvider> : ui}</SidebarProvider></I18nProvider>);
const links = () => screen.getAllByRole('link').map((l) => l.textContent?.trim());

// req: R-50
describe('my plan on', () => {
  it('my plan on shows "My plan" in rail, header, command menu, card and strip', async () => {
    plan(myPlanGermany);
    wrap(<>
      <OsNavGroup stageId="H" /><OsHeader workspaceId="ws1" current="os-inbox" title="T" />
      <OsPlanCard /><OsVaultStrip />
      <CommandMenu open onOpenChange={() => {}} onGo={() => {}} onAsk={() => {}} osOpen pages={myPlanGermany.pages} />
    </>);
    await waitFor(() => expect(screen.getAllByText('My plan').length).toBeGreaterThanOrEqual(5));
    expect(screen.queryByText('Study abroad plan')).toBeNull();
    expect(document.querySelector('[aria-label="My plan"]')).toBeTruthy();
  });

  // req: R-51
  it('my plan on lists only the route\'s pages in route order with route labels', async () => {
    plan(myPlanPkBs);
    wrap(<OsNavGroup stageId="H" />);
    await screen.findByText('My plan');
    expect(links()).toEqual(['Inbox', 'Documents', 'Places']);
    expect(screen.queryByRole('link', { name: 'Visa' })).toBeNull();
    expect(screen.getAllByRole('link').map((l) => l.getAttribute('href')))
      .toEqual(['/ws1/os-inbox', '/ws1/os-documents', '/ws1/os-programmes']);
  });

  it('the phone menu lists the route\'s pages too', async () => {
    plan(myPlanPkBs);
    wrap(<OsHeader workspaceId="ws1" current="os-inbox" title="T" />);
    await screen.findByText('My plan');
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(links()).toEqual(['Inbox', 'Documents', 'Places', 'Back to the main menu']);
  });

  // req: R-52
  it('germany with my plan on keeps today\'s labels and titles', async () => {
    plan(myPlanGermany);
    wrap(<OsNavGroup stageId="H" />);
    await screen.findByText('My plan');
    expect(links()).toEqual(['Start', 'Inbox', 'Documents', 'Programmes', 'Statements', 'Pack', 'Visa']);
    const today: Record<string, string> = { start: 'Start your plan', inbox: 'Your next steps', documents: 'Your documents',
      programmes: 'Your programmes', statements: 'Your statement and CV', pack: 'Your application packs', visa: 'Your visa file' };
    for (const [key, title] of Object.entries(today)) expect(pageTitle(myPlanGermany, key, 'x')).toBe(title);
  });

  // req: R-53
  it('visible before stage H when my plan is on', async () => {
    plan(myPlanEmpty);
    wrap(<OsNavGroup stageId="B" />);
    expect(await screen.findByText('My plan')).toBeTruthy();
    expect(screen.getByText(copy.connect.myPlan.empty)).toBeTruthy();
    expect(screen.getByRole('link', { name: copy.connect.myPlan.emptyLink }).getAttribute('href')).toBe('/ws1?view=journey');
  });

  it('plan card shows empty state before a choice', async () => {
    plan(myPlanEmpty);
    vi.mocked(workspaceApi.getOsInbox).mockResolvedValue([]);
    wrap(<OsPlanCard />);
    expect(await screen.findByText(copy.connect.myPlan.empty)).toBeTruthy();
    expect(screen.getByText('My plan')).toBeTruthy();
  });

  it('the command menu has no my plan group before a choice', async () => {
    plan(myPlanEmpty);
    wrap(<CommandMenu open onOpenChange={() => {}} onGo={() => {}} onAsk={() => {}} osOpen={false} pages={[]} />);
    expect(screen.queryByText('My plan')).toBeNull();
  });

  it('a page outside the plan shows only the not-in-plan line', async () => {
    plan(myPlanPkBs);
    wrap(<NotInPlan workspaceId="ws1" />);
    await waitFor(() => expect(screen.getByRole('link').getAttribute('href')).toBe('/ws1/os-inbox'));
    expect(screen.getByText(copy.connect.myPlan.notInPlan)).toBeTruthy();
    expect(screen.getByRole('link', { name: copy.connect.myPlan.notInPlanLink })).toBeTruthy();
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('card and strip show no plane icon when my plan is on', async () => {
    plan(myPlanPkBs);
    const { container } = wrap(<><OsPlanCard /><OsVaultStrip /></>);
    await waitFor(() => expect(container.querySelectorAll('section').length).toBe(2));
    expect(container.querySelector('svg.lucide-plane')).toBeNull();
    expect(container.querySelector('svg.lucide-list-checks')).toBeTruthy();
  });

  it('pack noun comes from the route', () => {
    expect(pageNoun(myPlanGermany, 'visa', 'x')).toBe('visa file');
    expect(pageNoun(myPlanGermany, 'pack', 'x')).toBe('pack');
    expect(pageNoun(myPlanPkBs, 'pack', 'pack')).toBe('pack');
  });
});

describe('my plan off', () => {
  const surfaces = (provider: boolean) => wrap(<>
    <OsNavGroup stageId="H" /><OsHeader workspaceId="ws1" current="os-inbox" title="T" /><OsPlanCard /><OsVaultStrip />
  </>, provider);

  it('my plan 404, error or loading renders today\'s markup', async () => {
    for (const answer of [new Error('API 404: Not Found'), new Error('API 500'), [], { nope: 1 }]) {
      plan(answer);
      const before = surfaces(false);
      await screen.findAllByText('Study abroad plan');
      await waitFor(() => expect(before.container.querySelectorAll('section').length).toBe(2));
      const today = before.container.innerHTML;
      cleanup();
      plan(answer);
      const after = surfaces(true);
      await waitFor(() => expect(after.container.querySelectorAll('section').length).toBe(2));
      await new Promise((r) => setTimeout(r, 20));
      expect(after.container.innerHTML).toBe(today);
      expect(screen.queryByText('My plan')).toBeNull();
      cleanup();
    }
  });

  it('still loading renders today\'s markup', () => {
    vi.mocked(workspaceApi.getMyPlan).mockReturnValue(new Promise(() => {}));
    wrap(<OsNavGroup stageId="H" />);
    expect(screen.getByText('Study abroad plan')).toBeTruthy();
  });
});
