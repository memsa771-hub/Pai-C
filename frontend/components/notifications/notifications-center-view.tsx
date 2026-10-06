'use client';

import { useEffect, useState } from 'react';
import { Bell, CheckCheck, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { NotificationCard } from '@/components/notifications/notification-card';
import { useNotificationNavigation } from '@/components/notifications/use-notification-navigation';
import { workspaceApi } from '@/lib/api';
import type { NotificationItem } from '@/lib/types';
import { useWorkspace } from '@/lib/workspace-context';

const PAGE_SIZE = 50;

export function NotificationsCenterView() {
  const { unreadNotificationCount, refreshNotifications, markNotificationRead, markAllNotificationsRead, dismissNotification } = useWorkspace();
  const navigate = useNotificationNavigation();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    workspaceApi.listNotifications({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, isRead: filter === 'unread' ? false : undefined })
      .then((result) => {
        if (!active) return;
        setItems((previous) => page === 0 ? result.notifications : [...previous, ...result.notifications]);
        setHasMore(result.notifications.length === PAGE_SIZE);
        setError('');
      })
      .catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : 'Notifications could not load.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filter, page, revision]);

  const reload = () => { setPage(0); setRevision((value) => value + 1); void refreshNotifications(); };
  const act = async (operation: () => Promise<void>) => {
    try {
      setError('');
      await operation();
      reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not update notifications.');
    }
  };

  return <div className="h-full overflow-y-auto bg-background"><div className="mx-auto max-w-4xl px-5 py-8 sm:px-8 lg:py-10">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Student workspace</p><h1 className="mt-2 flex items-center gap-3 text-3xl font-semibold"><Bell className="size-7 text-primary" />Notifications</h1><p className="mt-2 text-sm text-muted-foreground">Deadline reminders and workspace updates in one place.</p></div>
      <div className="flex gap-2"><Button variant="outline" onClick={reload}><RefreshCw className="mr-1 size-4" />Refresh</Button><Button variant="outline" disabled={unreadNotificationCount === 0} onClick={() => void act(markAllNotificationsRead)}><CheckCheck className="mr-1 size-4" />Mark all read</Button></div>
    </div>
    {error && <p className="mt-5 text-sm text-destructive" role="alert">{error}</p>}
    <div className="mt-7 flex gap-2 border-b pb-3"><Button size="sm" variant={filter === 'all' ? 'primary' : 'ghost'} onClick={() => { setFilter('all'); setPage(0); }}>All</Button><Button size="sm" variant={filter === 'unread' ? 'primary' : 'ghost'} onClick={() => { setFilter('unread'); setPage(0); }}>Unread ({unreadNotificationCount})</Button></div>
    {items.length === 0 && !loading ? <div className="mt-6 rounded-2xl border border-dashed p-10 text-center text-sm text-muted-foreground">{filter === 'unread' ? 'No unread notifications.' : 'No notifications yet.'}</div> : <div className="mt-4 divide-y rounded-2xl border bg-card">{items.map((item) => <NotificationCard key={item.id} notification={item} onRead={(id) => void act(() => markNotificationRead(id))} onDismiss={(id) => void act(() => dismissNotification(id))} onNavigate={(selected) => { void navigate(selected).then(() => { if (!selected.isRead) reload(); }); }} />)}</div>}
    {loading && <p role="status" className="mt-4 text-sm text-muted-foreground">Loading notifications…</p>}
    {hasMore && !loading && <Button className="mt-4" variant="outline" onClick={() => setPage((value) => value + 1)}>Load more</Button>}
  </div></div>;
}
