// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OsPlanCard } from './plan-card';
import { workspaceApi } from '@/lib/api';
import { I18nProvider } from '@/lib/i18n';
import type { Adoption } from '@/lib/os-connect';
import copy from '@/components/counselor/workspace/copy.json';

vi.mock('@/lib/config', () => ({ OS_UI_ENABLED: true }));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws-1' }) }));
vi.mock('@/lib/api', () => ({ workspaceApi: { getOsInbox: vi.fn(), getAdoption: vi.fn(), adoptPlan: vi.fn() } }));

// Fictional values only.
const TEXT = { offer: 'You built a plan yourself. Keep it as your PAI plan?', agree: 'Keep my plan',
               choose_field_first: 'Choose your field first.', too_many_places: 'Too many places.',
               linking: 'Your plan is being linked.' };
const offer = (over: Partial<Adoption> = {}): Adoption => ({ offer: true, state: 'ready', text: TEXT,
  plan: { plan_id: 9, route_key: 'r1', places: 2 }, ...over });
const ITEM = { id: 1, instance_key: 'collect_transcripts', title: 'Collect transcripts', kind: 'student', inbox_kind: 'act',
               programme_ref: null, state: 'ready', blocked_reason: null, due_at: null, due_tz: 'UTC', provisional: false,
               estimated: false, slack_days: null, critical: false, citations: [] };

function show() {
  return render(<I18nProvider><OsPlanCard /></I18nProvider>);
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function setup(adoption: Adoption | Error) {
  vi.mocked(workspaceApi.getOsInbox).mockResolvedValue([ITEM] as never);
  if (adoption instanceof Error) vi.mocked(workspaceApi.getAdoption).mockRejectedValue(adoption);
  else vi.mocked(workspaceApi.getAdoption).mockResolvedValue(adoption);
}

// req: R-08
describe('plan card adoption offer', () => {
  it('plan card shows adoption offer and agree calls adoptPlan', async () => {
    setup(offer());
    vi.mocked(workspaceApi.adoptPlan).mockResolvedValue({ state: 'linking', decision_version: 4 });
    show();
    expect(await screen.findByText(TEXT.offer)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: TEXT.agree }));
    await waitFor(() => expect(workspaceApi.adoptPlan).toHaveBeenCalledWith(9));
    expect(await screen.findByText(TEXT.linking)).toBeTruthy();
    expect(screen.getByText(copy.connect.adoption.linking_wait)).toBeTruthy();
    expect(screen.queryByRole('button', { name: TEXT.agree })).toBeNull();
  });

  it('no text means no offer', async () => {
    setup(offer({ text: null }));
    show();
    await screen.findByText(/Collect transcripts/);
    expect(screen.queryByRole('button', { name: TEXT.agree })).toBeNull();
    expect(screen.queryByText(TEXT.offer)).toBeNull();
  });

  it('offer false, a failing call and a missing call all leave the card as it was', async () => {
    for (const a of [{ offer: false, state: 'several_plans' } as Adoption, new Error('API 500')]) {
      setup(a);
      show();
      await screen.findByText(/Collect transcripts/);
      expect(document.querySelector('section[aria-label="' + TEXT.offer + '"]')).toBeNull();
      cleanup();
    }
    const saved = workspaceApi.getAdoption;
    try {
      (workspaceApi as { getAdoption?: unknown }).getAdoption = undefined;
      vi.mocked(workspaceApi.getOsInbox).mockResolvedValue([ITEM] as never);
      show();
      expect(await screen.findByText(/Collect transcripts/)).toBeTruthy();
    } finally {
      workspaceApi.getAdoption = saved;
    }
  });

  it('a linking offer shows its text and no button; a linked one says so', async () => {
    setup(offer({ state: 'linking' }));
    show();
    expect(await screen.findByText(TEXT.linking)).toBeTruthy();
    expect(screen.queryByRole('button', { name: TEXT.agree })).toBeNull();
    cleanup();
    setup(offer({ state: 'linked' }));
    show();
    expect(await screen.findByText(copy.connect.adoption.linked)).toBeTruthy();
  });

  it('a refused agree shows a plain message by its code', async () => {
    setup(offer());
    vi.mocked(workspaceApi.adoptPlan).mockRejectedValue(new Error('API 409: {"detail":"plan_changed"}'));
    show();
    fireEvent.click(await screen.findByRole('button', { name: TEXT.agree }));
    expect((await screen.findByRole('alert')).textContent).toBe(copy.connect.adoption.plan_changed);
    expect(screen.getByRole('button', { name: TEXT.agree })).toBeTruthy();
  });

  it.each(['choose_field_first', 'too_many_places'] as const)('state %s shows its text and no button', async (state) => {
    setup(offer({ state }));
    show();
    expect(await screen.findByText(TEXT[state])).toBeTruthy();
    expect(screen.queryByRole('button', { name: TEXT.agree })).toBeNull();
  });

  it('an unknown state renders no empty card', async () => {
    setup(offer({ state: 'something_new' }));
    show();
    await screen.findByText(/Collect transcripts/);
    expect(document.querySelectorAll('section').length).toBe(1);  // only the plan card itself
  });

  it.each(['several_plans', 'no_places', 'no_intake'] as const)('offer false with %s says why', async (state) => {
    setup({ offer: false, state });
    show();
    expect(await screen.findByText((copy.connect.adoption as Record<string, string>)[state])).toBeTruthy();
    expect(screen.queryByRole('button', { name: TEXT.agree })).toBeNull();
  });
});
