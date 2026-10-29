import { afterEach, expect, it, vi } from 'vitest';
import { workspaceApi } from './api';

vi.mock('./auth/service', async (original) => ({
  ...(await original<typeof import('./auth/service')>()),
  currentIdToken: async () => 'founder-bearer',
}));

afterEach(() => vi.unstubAllGlobals());

it('reads this month\'s spend from /v1/admin/usage', async () => {
  const data = { month: '2026-10', cap: 100, spent: 1.5, stage: 'ok', by_role: [{ role: 'counselor', calls: 3, est_usd: 1.5 }] };
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data }) });
  vi.stubGlobal('fetch', fetchMock);
  expect(await workspaceApi.getAdminUsage()).toEqual(data);
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/v1\/admin\/usage$/);
});

it('answers null for an account that is not a founder (403), and throws on other failures', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403, text: async () => '{"code":403,"message":"Founder access only"}' }));
  expect(await workspaceApi.getAdminUsage()).toBeNull();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => 'down' }));
  await expect(workspaceApi.getAdminUsage()).rejects.toThrow('API 500');
});
