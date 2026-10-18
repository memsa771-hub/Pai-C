'use client';

import { useLayout } from '@/components/layout/layout-context';
import type { NotificationItem } from '@/lib/types';
import { useWorkspace } from '@/lib/workspace-context';

/** Both notification surfaces use the same destinations and read behavior. */
export function useNotificationNavigation() {
  const { openView } = useLayout();
  const { markNotificationRead, sessions, setCurrentSessionId } = useWorkspace();

  return (item: NotificationItem) => {
    const read = item.isRead ? Promise.resolve() : markNotificationRead(item.id);
    if (item.createdBy === 'system:roadmaps') {
      openView('roadmaps');
    } else if (item.channelName && sessions.some((session) => session.sessionId === item.channelName)) {
      setCurrentSessionId(item.channelName);
      openView('threads');
    }
    return read;
  };
}
