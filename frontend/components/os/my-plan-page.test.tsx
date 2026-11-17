// @vitest-environment jsdom
import { Suspense } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import copy from '@/components/counselor/workspace/copy.json';
import { myPlanPkBs } from '../../tests/fixtures/counselor';
import { MyPlanContext } from './my-plan-context';
import OsVisaPage from '../../app/[workspaceId]/(os)/os-visa/page';

vi.mock('@/lib/config', () => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false, OS_FROM_STAGE: 'H' }));
vi.mock('@/lib/pai-auth-context', () => ({ usePaiAuth: () => ({ loading: false, user: { uid: 'u' }, idToken: 't' }) }));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }), useRouter: () => ({ push: vi.fn() }),
  notFound: vi.fn() }));
vi.mock('@/lib/api', () => ({ workspaceApi: { configure: vi.fn(), getOsVisa: vi.fn(), getVault: vi.fn() } }));

const params = Object.assign(Promise.resolve({ workspaceId: 'ws1' }), { status: 'fulfilled', value: { workspaceId: 'ws1' } });  // `use` reads it at once

afterEach(() => { cleanup(); vi.clearAllMocks(); });

// req: R-51
describe('a real OS page outside the plan', () => {
  it('os-visa under a plan without visa shows only the not-in-plan line and calls nothing', async () => {
    vi.mocked(workspaceApi.getOsVisa).mockResolvedValue({} as never);
    vi.mocked(workspaceApi.getVault).mockResolvedValue({} as never);
    const { container } = render(<I18nProvider>
      <MyPlanContext.Provider value={{ on: true, plan: myPlanPkBs, refresh() {} }}>
        <Suspense fallback={null}><OsVisaPage params={params} /></Suspense>
      </MyPlanContext.Provider></I18nProvider>);
    await screen.findByText(copy.connect.myPlan.notInPlan);
    await new Promise((r) => setTimeout(r, 30));
    expect(container.textContent).toBe(
      `${copy.connect.myPlan.notInPlanTitle}${copy.connect.myPlan.notInPlan}${copy.connect.myPlan.notInPlanLink}`);
    expect(workspaceApi.getOsVisa).not.toHaveBeenCalled();
    expect(workspaceApi.getVault).not.toHaveBeenCalled();
    expect(workspaceApi.configure).not.toHaveBeenCalled();
  });
});
