// @vitest-environment jsdom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, renderHook } from '@testing-library/react';
import { useDesktopWorkspaceState } from './use-desktop-workspace-state';
import { useNotificationNavigation } from '../notifications/use-notification-navigation';
import type { NotificationItem } from '@/lib/types';

const state = vi.hoisted(() => ({
  openView: vi.fn(), markNotificationRead: vi.fn(), setCurrentSessionId: vi.fn(),
  sessions: [{ sessionId: 'pai-counselor' }],
}));
vi.mock('@/lib/i18n', () => ({ useT: () => (key: string) => key }));
vi.mock('./layout-context', () => ({ useLayout: () => ({ viewMode: 'threads', openView: state.openView }) }));
vi.mock('@/lib/workspace-context', () => ({ useWorkspace: () => ({
  ...state, files: [], loading: false, currentSessionId: 'pai-counselor',
}) }));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'test-workspace' }) }));
vi.mock('@/lib/pai-auth-context', () => ({ usePaiAuth: () => ({ user: { email: 'offline@example.invalid' } }) }));
vi.mock('@/lib/desktop-host', () => ({ desktopHost: () => ({}) }));

const preferenceKey = 'oa:desktop:view:offline@example.invalid:test-workspace';
const notification = (overrides: Partial<NotificationItem> = {}): NotificationItem => ({
  id: 'notice', title: '', message: '', priority: 'normal', isRead: false,
  createdBy: 'system', channelName: null, threadId: null, linkUrl: null,
  status: 'open', createdAt: null, readAt: null, ...overrides,
});
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); state.markNotificationRead.mockResolvedValue(undefined); });
afterEach(cleanup);

it.each(['applications', 'deadlines', 'tasks', 'workflows'])('ignores an old saved %s view while retaining the Counselor session', (view) => {
  localStorage.setItem(preferenceKey, JSON.stringify({ view, thread: 'pai-counselor' }));
  renderHook(useDesktopWorkspaceState);
  expect(state.openView).not.toHaveBeenCalled();
  expect(state.setCurrentSessionId).toHaveBeenCalledWith('pai-counselor', { skipFocus: true });
});

it.each(['roadmaps', 'roadmap', 'compare', 'plan'])('restores a saved %s view on the one Roadmap page', (view) => {
  localStorage.setItem(preferenceKey, JSON.stringify({ view }));
  renderHook(useDesktopWorkspaceState);
  expect(state.openView).toHaveBeenCalledWith('roadmap');
});

it.each([
  { createdBy: 'system:deadline' }, { channelName: 'task:old-task' },
])('marks a historical OS notification read without opening a removed screen: %j', async (fields) => {
  const { result } = renderHook(useNotificationNavigation);
  await result.current(notification(fields));
  expect(state.markNotificationRead).toHaveBeenCalledWith('notice');
  expect(state.openView).not.toHaveBeenCalled();
});

it('keeps roadmap notifications and Counselor conversation navigation', async () => {
  const { result } = renderHook(useNotificationNavigation);
  await result.current(notification({ createdBy: 'system:roadmaps' }));
  expect(state.openView).toHaveBeenLastCalledWith('roadmap');
  await result.current(notification({ channelName: 'pai-counselor', isRead: true }));
  expect(state.setCurrentSessionId).toHaveBeenCalledWith('pai-counselor');
  expect(state.openView).toHaveBeenLastCalledWith('threads');
  expect(state.markNotificationRead).toHaveBeenCalledTimes(1);
});
