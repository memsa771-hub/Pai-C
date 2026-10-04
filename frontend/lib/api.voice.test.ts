import { afterEach, expect, it, vi } from 'vitest';
import { workspaceApi } from './api';

afterEach(() => vi.unstubAllGlobals());

it('sends speech as the same authenticated student message event as text', async () => {
  workspaceApi.configure('workspace', '', 'student-bearer');
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ data: { id: 'event-1' } }),
  });
  vi.stubGlobal('fetch', fetchMock);
  await workspaceApi.sendCounselorVoiceTurn('pai-counselor', 'I want to study CS', 'delegation-1', 'Student', 'owner');
  const [url, options] = fetchMock.mock.calls[0];
  const body = JSON.parse(options.body);
  expect(url).toMatch(/\/v1\/events$/);
  expect(options.headers.Authorization).toBe('Bearer student-bearer');
  expect(body).toMatchObject({
    network: 'workspace', type: 'workspace.message.posted',
    target: 'channel/pai-counselor', visibility: 'channel',
    payload: { content: 'I want to study CS', sender_type: 'human' },
    metadata: { target_agents: ['pai'], voice_delegation_id: 'delegation-1' },
  });
});
