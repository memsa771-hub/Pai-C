// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SidebarProvider } from '@/components/ui/sidebar';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import routes from '../../tests/fixtures/my-plan-routes.json';
import { MyPlanProvider } from './my-plan-context';
import { OsNavGroup } from './os-nav-group';
import { OsHeader } from './os-header';
import { OsPlanCard } from './plan-card';
import { OsVaultStrip } from './vault-strip';
import { InboxList } from './inbox-list';
import { CommandMenu } from '@/components/counselor/workspace/shell-parts';
import { RouteSteps } from '@/components/counselor/workspace/roadmap-steps';

// The label test, frontend half (P1-T9, R-55, with R-50 and R-52). The routes, their words and what each route says
// come from tests/fixtures/my-plan-routes.json, which backend/tests/os/test_route_label_fixture.py builds from the four
// playbooks and the word list (so there is one word list). Every My plan surface is rendered for each route.
// The rule below is the TS copy of `foreign_words` and `abroad_words` in backend/tests/os/route_labels.py.

type Words = Record<string, { country: string[]; bodies: string[]; documents: string[] }>;
type Route = (typeof routes)[number];

const flat = (words: Words, route: string) => [...words[route].country, ...words[route].bodies, ...words[route].documents];
const pattern = (word: string) => new RegExp(
  `(?<!\\w)${word.trim().split(/[\s-]+/).map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[\\s-]+')}(?!\\w)`, 'i');
const same = (a: string, b: string) => new RegExp(`^${pattern(a).source}$`, 'i').test(b) || new RegExp(`^${pattern(b).source}$`, 'i').test(a);
export function foreignWords(route: string, text: string, words: Words): string[] {
  const own = flat(words, route);
  const found: string[] = [];
  for (const other of Object.keys(words)) {
    if (other === route) continue;
    for (const word of flat(words, other)) {
      if (own.some((mine) => same(word, mine))) continue;
      if (pattern(word).test(text) && !found.includes(word)) found.push(word);
    }
  }
  return found;
}
export const abroadWords = (text: string) => [...new Set((text.match(/abroad|visa/gi) ?? []).map((w) => w.toLowerCase()))].sort();

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
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const DOCS = { documents: [{ id: 1, doc_type: 'passport', status: 'confirmed' }], doc_types: [{ key: 'passport', label: 'Passport' }] };

/** The fixture's items as the inbox API gives them (the fixture holds what the playbook says; the rest is plumbing). */
const inboxItems = (route: Route) => route.items.map((item, i) => {
  const waiting = 'waiting_for' in item;
  return {
    id: i + 1, instance_key: `k${i}`, title: item.title, kind: 'student', inbox_kind: item.inbox_kind, programme_ref: null,
    state: waiting ? 'blocked' : 'ready', blocked_reason: waiting ? `fact_missing:${(item as { fact: string }).fact}` : null,
    due_at: waiting ? null : '2027-06-18T21:59:59Z', due_tz: 'UTC', provisional: false, estimated: false,
    slack_days: null, critical: false, citations: 'citations' in item ? item.citations : [],
    ...(waiting ? { waiting_for: (item as { waiting_for: string }).waiting_for } : {}),
  };
});
const routeSteps = (route: Route) => route.steps.map((s, i) => ({
  key: `s${i}`, kind: 'os', label_key: '', values: {}, status: 'not' as const, title: s.title, owner: s.owner as 'student' | 'pai' }));

/** Every My plan surface of a route, rendered inside a MyPlanProvider answering that route's plan. */
async function renderRoute(route: Route, tweak: { plan?: unknown; items?: unknown[] } = {}) {
  const plan = (tweak.plan ?? route.plan) as { pages: { key: string; label: string }[] };
  vi.mocked(workspaceApi.getMyPlan).mockResolvedValue(plan as never);
  const items = tweak.items ?? inboxItems(route);
  vi.mocked(workspaceApi.getOsInbox).mockResolvedValue(items as never);
  vi.mocked(workspaceApi.getAdoption).mockResolvedValue({ offer: false } as never);
  vi.mocked(workspaceApi.getOsDocuments).mockResolvedValue(DOCS as never);
  const view = render(
    <I18nProvider><SidebarProvider><MyPlanProvider>
      <OsNavGroup stageId="B" />
      <OsNavGroup stageId="B" collapsed />
      {plan.pages.map((p) => <OsHeader key={p.key} workspaceId="ws1" current={`os-${p.key}` as never} title={(p as unknown as { title: string }).title} />)}
      <CommandMenu open onOpenChange={() => {}} onGo={() => {}} onAsk={() => {}} osOpen pages={plan.pages} />
      <OsPlanCard />
      <OsVaultStrip />
      <InboxList items={items as never} now={new Date('2027-06-01T00:00:00Z')} onComplete={() => {}} />
      <RouteSteps steps={routeSteps(route) as never} label="Steps" />
    </MyPlanProvider></SidebarProvider></I18nProvider>);
  await waitFor(() => expect(view.container.querySelectorAll('section[aria-label="My plan"]').length).toBe(2));
  for (const button of document.querySelectorAll('button[aria-controls="os-menu"]')) fireEvent.click(button);  // the phone menus
  return view;
}

/** Everything a student could read: the page text and every aria-label. */
const words = (): string => [document.body.textContent ?? '',
  ...[...document.body.querySelectorAll('[aria-label]')].map((e) => e.getAttribute('aria-label') ?? '')].join('\n');

const ROUTES = routes as Route[];
const WORDS = ROUTES[0].words as Words;
const stays = ROUTES.filter((r) => !r.abroad);

describe('every route renders only its own words', () => {
  // req: R-55, R-52
  it.each(ROUTES.map((r) => [r.route_key, r] as const))('%s: no route renders another route\'s country, body or document name', async (_key, route) => {
    await renderRoute(route);
    expect(foreignWords(route.route_key, words(), route.words as Words)).toEqual([]);
  });

  it('the fixture has the four routes, two of them staying in one country, and each says its own words', () => {
    expect(ROUTES.map((r) => r.route_key)).toEqual(['germany_master', 'ireland_master', 'pakistan_bs', 'pakistan_inter']);
    expect(stays.map((r) => r.route_key)).toEqual(['pakistan_bs', 'pakistan_inter']);
    expect(JSON.stringify(ROUTES[0].items)).toContain('uni-assist');
    expect(JSON.stringify(ROUTES[2].items)).toContain('entry test');
  });

  // req: R-50, R-52
  it.each(stays.map((r) => [r.route_key, r] as const))('%s: non-abroad routes render no abroad, no visa and no plane icon', async (_key, route) => {
    const { container } = await renderRoute(route);
    expect(abroadWords(words())).toEqual([]);
    expect(container.querySelector('svg.lucide-plane')).toBeNull();
    expect(document.body.querySelector('svg.lucide-plane')).toBeNull();
  });

  // req: R-50
  it.each(ROUTES.map((r) => [r.route_key, r] as const))('%s: says My plan, never Study abroad plan', async (_key, route) => {
    await renderRoute(route);
    expect(document.body.textContent!.split('My plan').length - 1).toBeGreaterThanOrEqual(5);
    expect(document.querySelector('[aria-label="My plan"]')).toBeTruthy();
    expect(words()).not.toContain('Study abroad plan');
  });

  it('a route that leaves the country may say visa, so the rule is not just empty', async () => {
    await renderRoute(ROUTES[0]);
    expect(abroadWords(words())).toContain('visa');
    expect(words()).toMatch(/uni-assist/i);  // its own word is rendered and allowed
  });
});

describe('the label rule catches a planted word', () => {
  // req: R-55
  it('another route\'s body in a PK BS title', async () => {
    const route = ROUTES[2];
    const items = inboxItems(route);
    items[0] = { ...items[0], title: 'Submit to uni-assist' };
    await renderRoute(route, { items });
    expect(foreignWords(route.route_key, words(), route.words as Words)).toEqual(['uni-assist']);
  });

  it('a country and a document in an Irish step, and a hyphen counts as a space', async () => {
    const route = ROUTES[1];
    const items = inboxItems(route);
    items[0] = { ...items[0], title: 'Get a German Blocked-Account' };
    await renderRoute(route, { items });
    expect(foreignWords(route.route_key, words(), route.words as Words)).toEqual(['German', 'blocked account']);
  });

  it('its own words are allowed, and a word shared by two routes is allowed on both', () => {
    expect(foreignWords('germany_master', 'Your German uni-assist blocked account', WORDS)).toEqual([]);
    expect(foreignWords('pakistan_inter', 'Choose from the merit-list offers', WORDS)).toEqual([]);
    expect(foreignWords('pakistan_inter', 'Sit the entry test', WORDS)).toEqual(['entry test']);
    expect(foreignWords('pakistan_bs', 'Studying in Germany is not Germanic', WORDS)).toEqual(['Germany']);
  });

  it('abroad, visa and a plane icon on a route that stays in one country', async () => {
    const route = ROUTES[2];
    const visa = { key: 'visa', label: 'Visa', title: 'Your visa file', noun: 'visa file' };
    const items = inboxItems(route);
    items[0] = { ...items[0], title: 'Study abroad' };
    const { container } = await renderRoute(route, { plan: { ...route.plan, pages: [...route.plan.pages, visa] }, items });
    expect(abroadWords(words())).toEqual(['abroad', 'visa']);
    expect(container.querySelector('svg.lucide-plane')).not.toBeNull();  // the Visa page link keeps its plane
  });
});
