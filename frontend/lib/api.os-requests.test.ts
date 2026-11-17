import { afterEach, expect, it, vi } from 'vitest';
import { workspaceApi } from './api';

vi.mock('./auth/service', async (original) => ({
  ...(await original<typeof import('./auth/service')>()),
  currentIdToken: async () => 'student-bearer',
}));

afterEach(() => vi.unstubAllGlobals());

// req: R-19
it('no requests endpoint means today\'s inbox (404 is null)', async () => {
  workspaceApi.configure('workspace', '', 'student-bearer');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => '{"detail":"Not Found"}' }));
  expect(await workspaceApi.getOsRequests()).toBeNull();
});

// req: R-19
it('other errors are not hidden', async () => {
  workspaceApi.configure('workspace', '', 'student-bearer');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => 'boom' }));
  await expect(workspaceApi.getOsRequests()).rejects.toThrow('API 500');
});

// req: R-21
it('an answer sends the choice with the question it saw, and a typed value only when given', async () => {
  workspaceApi.configure('workspace', '', 'student-bearer');
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'answered' }) });
  vi.stubGlobal('fetch', fetchMock);
  await workspaceApi.answerOsRequest(4, 'proposed', { ref: 'card-1', seen: 'abc' });
  await workspaceApi.answerOsRequest(4, 'new', { ref: 'card-1', seen: 'abc' }, 770);
  const [url, options] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/v1\/os\/requests\/4\/answer\?/);
  expect(JSON.parse(options.body)).toEqual({ choice: 'proposed', ref: 'card-1', seen: 'abc' });
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ choice: 'new', ref: 'card-1', seen: 'abc', value: 770 });
});
