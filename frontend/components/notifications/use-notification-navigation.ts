'use client';

import { useLayout } from '@/components/layout/layout-context';
import { TASKS_UI_ENABLED } from '@/lib/config';
import type { NotificationItem } from '@/lib/types';
import { useWorkspace } from '@/lib/workspace-context';

/** Both notification surfaces use the same destinations and read behavior. */
export function useNotificationNavigation() {
  const { openView, setPendingTaskChannel } = useLayout();
  const { markNotificationRead, sessions, setCurrentSessionId } = useWorkspace();

  return (item: NotificationItem) => {
    const read = item.isRead ? Promise.resolve() : markNotificationRead(item.id);
    if (item.createdBy === 'system:deadline') {
      openView('deadlines');
    } else if (TASKS_UI_ENABLED && item.channelName?.startsWith('task:')) {
      setPendingTaskChannel(item.channelName);
      openView('tasks');
    } else if (item.channelName && sessions.some((session) => session.sessionId === item.channelName)) {
      setCurrentSessionId(item.channelName);
      openView('threads');
    }
    return read;
  };
}
