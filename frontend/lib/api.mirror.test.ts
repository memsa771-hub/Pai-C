import { afterEach, expect, it, vi } from 'vitest';
import { workspaceApi } from './api';

afterEach(() => vi.unstubAllGlobals());

it('uses authenticated versioned Confirm/Edit endpoints', async () => {
  workspaceApi.configure('workspace', '', 'student-bearer');
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { status: 'confirmed' } }) });
  vi.stubGlobal('fetch', fetch);
  await workspaceApi.confirmCounselorMirror(2);
  await workspaceApi.editCounselorMirror(2, 'A correction.');
  expect(fetch.mock.calls[0][0]).toContain('/v1/counselor/summary/confirm?network=workspace');
  expect(fetch.mock.calls[1][0]).toContain('/v1/counselor/summary/edit?network=workspace');
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer student-bearer');
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ version: 2 });
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ version: 2, text: 'A correction.' });
});
