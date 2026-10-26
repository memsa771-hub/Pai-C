'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { desktopHost } from '@/lib/desktop-host';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { useWorkspace } from '@/lib/workspace-context';
import { useLayout, type ViewMode } from './layout-context';

const VIEWS: ViewMode[] = ['threads', 'roadmap', 'profile', 'notifications', 'files', 'inbox'];
/** Older saved views that now live on the one Roadmap page. */
const RENAMED: Record<string, ViewMode> = { roadmaps: 'roadmap', compare: 'roadmap', plan: 'roadmap' };

/** Desktop restore state only; web layout, data loading, and UI stay shared. */
export function useDesktopWorkspaceState(): void {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { user } = usePaiAuth();
  const { loading, sessions, currentSessionId, setCurrentSessionId } = useWorkspace();
  const { viewMode, openView } = useLayout();
  const [restored, setRestored] = useState('');
  const key = user && desktopHost() ? `oa:desktop:view:${user.email}:${workspaceId}` : '';

  useEffect(() => {
    if (!key || loading || restored === key) return;
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      const view = saved && (RENAMED[saved.view] || saved.view);
      if (view && VIEWS.includes(view)) openView(view);
      if (typeof saved?.thread === 'string' && sessions.some(s => s.sessionId === saved.thread)) {
        setCurrentSessionId(saved.thread, { skipFocus: true });
      }
    } catch { /* A malformed preference cannot prevent opening a workspace. */ }
    setRestored(key);
  }, [key, loading, restored, sessions, openView, setCurrentSessionId]);

  useEffect(() => {
    if (!key || loading || restored !== key) return;
    try { localStorage.setItem(key, JSON.stringify({ view: viewMode, thread: currentSessionId })); }
    catch { /* Optional preference. */ }
  }, [key, loading, restored, viewMode, currentSessionId]);
}
