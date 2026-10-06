'use client';

import { ExternalLink, X } from 'lucide-react';
import type { NotificationItem } from '@/lib/types';

function safeLink(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export function NotificationCard({ notification, onRead, onDismiss, onNavigate }: {
  notification: NotificationItem;
  onRead: (id: string) => void;
  onDismiss: (id: string) => void;
  onNavigate: (item: NotificationItem) => void;
}) {
  const link = safeLink(notification.linkUrl);
  return <article className={`flex items-start gap-3 p-3 ${notification.isRead ? '' : 'bg-primary/5'}`}>
    <div className="min-w-0 flex-1">
      <button type="button" className="w-full text-left" onClick={() => onNavigate(notification)}>
        <span className="flex items-center gap-2 text-sm font-semibold">
          {notification.title}
          {!notification.isRead && <span className="size-2 shrink-0 rounded-full bg-primary" aria-label="Unread" />}
        </span>
        <span className="mt-1 block text-xs text-muted-foreground">{notification.message}</span>
        <span className="mt-2 block text-[11px] text-muted-foreground">
          {notification.createdBy === 'system:deadline' ? 'Deadline reminder' : 'Workspace update'}
          {notification.createdAt && ` · ${new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(notification.createdAt))}`}
        </span>
      </button>
      {link && <a href={link} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs text-primary underline">
        <ExternalLink className="size-3" /> Open link
      </a>}
      {!notification.isRead && <button type="button" className="ml-3 text-xs text-muted-foreground underline" onClick={() => onRead(notification.id)}>Mark read</button>}
    </div>
    <button type="button" onClick={() => onDismiss(notification.id)} className="rounded-md p-1 text-muted-foreground hover:bg-muted" aria-label={`Dismiss ${notification.title}`}><X className="size-4" /></button>
  </article>;
}
