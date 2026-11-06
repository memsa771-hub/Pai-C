// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SidebarProvider } from '@/components/ui/sidebar';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import copy from '@/components/counselor/workspace/copy.json';
import { myPlanEmpty, myPlanGermany, myPlanPkBs } from '../../tests/fixtures/counselor';
import { MyPlanContext, MyPlanProvider, useMyPlan } from './my-plan-context';
import { OsNavGroup, osMenuOpen } from './os-nav-group';
import { OsHeader } from './os-header';
import { OsPlanCard } from './plan-card';
import { OsVaultStrip } from './vault-strip';
import { NotInPlan } from './not-in-plan';
import { CommandMenu } from '@/components/counselor/workspace/shell-parts';
import { asMyPlan, pageNoun, pageTitle } from '@/lib/os-my-plan';

const config = vi.hoisted(() => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false }));
const auth = vi.hoisted(() => ({ loading: false, user: { uid: 'u' } as object | null, idToken: 'tok' }));
vi.mock('@/lib/pai-auth-context', () => ({ usePaiAuth: () => auth }));
vi.mock('@/lib/config', () => ({
  get OS_UI_ENABLED() { return config.OS_UI_ENABLED; },
  get OS_REHEARSAL_UI() { return config.OS_REHEARSAL_UI; },
  OS_FROM_STAGE: 'H',
}));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }), useRouter: () => ({ push: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ workspaceApi: {
  isConfigured: vi.fn(() => true), getMyPlan: vi.fn(), getOsInbox: vi.fn(), getAdoption: vi.fn(), getOsDocuments: vi.fn() } }));

beforeAll(() => {
  window.matchMedia ??= ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  window.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as never;
  Element.prototype.scrollIntoView ??= () => {};
});
afterEach(() => { cleanup(); vi.clearAllMocks(); auth.loading = false; auth.user = { uid: 'u' }; vi.mocked(workspaceApi.isConfigured).mockReturnValue(true); config.OS_UI_ENABLED = true; config.OS_REHEARSAL_UI = false; });

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

  it('the command menu has no my plan group before a choice, and the open rule follows the part', () => {
    const on = (plan: typeof myPlanEmpty) => ({ on: true, plan, refresh() {} });
    expect(osMenuOpen(on(myPlanEmpty), 'B')).toBe(false);
    expect(osMenuOpen(on(myPlanPkBs), 'B')).toBe(true);
    expect(osMenuOpen({ on: false, plan: null, refresh() {} }, 'B')).toBe(false);
    expect(osMenuOpen({ on: false, plan: null, refresh() {} }, 'H')).toBe(true);
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

  it('a collapsed rail with no pages renders nothing', async () => {
    plan(myPlanEmpty);
    const { container } = wrap(<OsNavGroup stageId="B" collapsed />);
    await new Promise((r) => setTimeout(r, 20));
    expect(container.querySelector('[role="group"]')).toBeNull();
  });

  it('a page key without an icon falls back, and unknown keys never reach a plan', () => {
    const odd = { ...myPlanPkBs, pages: [{ key: 'zzz', label: 'Odd', title: 'Odd', noun: null }] };
    const { container } = render(<I18nProvider><SidebarProvider>
      <MyPlanContext.Provider value={{ on: true, plan: odd, refresh() {} }}><OsNavGroup /></MyPlanContext.Provider>
    </SidebarProvider></I18nProvider>);
    expect(screen.getByRole('link', { name: 'Odd' })).toBeTruthy();
    expect(container.querySelector('a svg')).toBeTruthy();
    expect(asMyPlan(odd)!.pages).toEqual([]);
    expect(asMyPlan({ ...myPlanPkBs, pages: [{ key: 'inbox', label: 3, title: 'x' }, ...myPlanPkBs.pages] })!.pages)
      .toHaveLength(3);
  });

  it('not-in-plan has a heading', () => {
    plan(myPlanPkBs);
    wrap(<NotInPlan workspaceId="ws1" />);
    expect(screen.getByRole('heading').textContent).toBe(copy.connect.myPlan.notInPlanTitle);
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

describe('my plan provider timing', () => {
  it('auth still loading means no fetch; auth ready means one fetch', async () => {
    plan(myPlanPkBs);
    auth.loading = true;
    const view = wrap(<OsNavGroup stageId="H" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(workspaceApi.getMyPlan).not.toHaveBeenCalled();
    auth.loading = false;
    view.rerender(<I18nProvider><SidebarProvider><MyPlanProvider><OsNavGroup stageId="H" /></MyPlanProvider></SidebarProvider></I18nProvider>);
    await screen.findByText('My plan');
    expect(workspaceApi.getMyPlan).toHaveBeenCalledTimes(1);
  });

  it('a workspace that is not set up yet is waited for, not answered as off', async () => {
    plan(myPlanPkBs);
    vi.mocked(workspaceApi.isConfigured).mockReturnValue(false);
    wrap(<OsNavGroup stageId="H" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(workspaceApi.getMyPlan).not.toHaveBeenCalled();
    vi.mocked(workspaceApi.isConfigured).mockReturnValue(true);
    await screen.findByText('My plan', undefined, { timeout: 2000 });
    expect(workspaceApi.getMyPlan).toHaveBeenCalledTimes(1);
  });

  it('after refresh() with a new answer, the rail shows the pages', async () => {
    plan(myPlanEmpty);
    function Again() { const { refresh } = useMyPlan(); return <button onClick={refresh}>again</button>; }
    wrap(<><OsNavGroup stageId="H" /><Again /></>);
    await screen.findByText(copy.connect.myPlan.empty);
    vi.mocked(workspaceApi.getMyPlan).mockResolvedValue(myPlanPkBs as never);
    fireEvent.click(screen.getByText('again'));
    await screen.findByRole('link', { name: 'Places' });
    expect(links()).toEqual(['again', 'Inbox', 'Documents', 'Places'].slice(1));
  });
});
