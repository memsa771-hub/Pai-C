// @vitest-environment jsdom
/** Audit #12 (not reproduced; watch): the desktop view restore is the one
 * effect that opens a view without a click. It keeps a guard: never over a
 * link's own ?view=, and only once, as the workspace first opens. */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, renderHook } from '@testing-library/react';
import { useDesktopWorkspaceState } from './use-desktop-workspace-state';

const state = vi.hoisted(() => ({
  openView: vi.fn(), setCurrentSessionId: vi.fn(), loading: false, user: { email: 'offline@example.invalid' } as { email: string } | null,
  sessions: [{ sessionId: 'pai-counselor' }],
}));
vi.mock('./layout-context', () => ({ useLayout: () => ({ viewMode: 'threads', openView: state.openView }) }));
vi.mock('@/lib/workspace-context', () => ({ useWorkspace: () => ({
  loading: state.loading, sessions: state.sessions, currentSessionId: 'pai-counselor', setCurrentSessionId: state.setCurrentSessionId,
}) }));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'test-workspace' }) }));
vi.mock('@/lib/pai-auth-context', () => ({ usePaiAuth: () => ({ user: state.user }) }));
vi.mock('@/lib/desktop-host', () => ({ desktopHost: () => ({}) }));

const key = 'oa:desktop:view:offline@example.invalid:test-workspace';
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); state.loading = false; state.user = { email: 'offline@example.invalid' };
  localStorage.setItem(key, JSON.stringify({ view: 'roadmap' }));
});
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

it('audit #12: a link with its own ?view= is never overridden by the saved view', () => {
  window.history.replaceState({}, '', '/w?view=profile');
  renderHook(useDesktopWorkspaceState);
  expect(state.openView).not.toHaveBeenCalled();
});

it('audit #12: the saved view still opens once, as the workspace first opens', () => {
  const { rerender } = renderHook(useDesktopWorkspaceState);
  rerender();
  expect(state.openView).toHaveBeenCalledTimes(1);
  expect(state.openView).toHaveBeenCalledWith('roadmap');
});
