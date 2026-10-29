'use client';

import { useEffect, useRef, useState } from 'react';
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
  // The saved view is restored only once, as the workspace first opens, and a
  // link's own ?view= wins (a guard kept for audit #12, which was not
  // reproduced: the workspace mounts only after auth, so a late key cannot
  // arrive mid-chat in the shipped flow).
  const initialView = useRef(viewMode);
  const opened = useRef(false);

  useEffect(() => {
    if (loading) return;
    if (!key) { opened.current = true; return; }
    if (restored === key) return;
    const untouched = !opened.current && viewMode === initialView.current
      && !new URLSearchParams(window.location.search).get('view');
    opened.current = true;
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      const view = saved && (RENAMED[saved.view] || saved.view);
      if (untouched && view && VIEWS.includes(view)) openView(view);
      if (untouched && typeof saved?.thread === 'string' && sessions.some(s => s.sessionId === saved.thread)) {
        setCurrentSessionId(saved.thread, { skipFocus: true });
      }
    } catch { /* A malformed preference cannot prevent opening a workspace. */ }
    setRestored(key);
  }, [key, loading, restored, sessions, openView, setCurrentSessionId, viewMode]);

  useEffect(() => {
    if (!key || loading || restored !== key) return;
    try { localStorage.setItem(key, JSON.stringify({ view: viewMode, thread: currentSessionId })); }
    catch { /* Optional preference. */ }
  }, [key, loading, restored, viewMode, currentSessionId]);
}
