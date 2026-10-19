'use client';

import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  GROUP_TITLES,
  KIND_LABELS,
  dateLabels,
  formatDue,
  groupItems,
  sourceHost,
  type OsInboxItem,
} from '@/lib/os-inbox';

interface InboxListProps {
  items: OsInboxItem[];
  now: Date;
  onComplete: (item: OsInboxItem) => void;
  busyId?: number | null;
}

/** The PAI OS student inbox (Slice 1 spec §4.11): mobile-first, one action per item. */
export function InboxList({ items, now, onComplete, busyId = null }: InboxListProps) {
  if (items.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted-foreground">Nothing to do right now.</p>;
  }
  return (
    <div className="flex flex-col gap-6">
      {groupItems(items, now).map(({ group, items: groupItemsList }) => (
        <section key={group} aria-label={GROUP_TITLES[group]}>
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {GROUP_TITLES[group]}
          </h2>
          <ul className="flex flex-col gap-2">
            {groupItemsList.map((item) => {
              const due = formatDue(item);
              const labels = dateLabels(item);
              const source = item.citations[0];
              return (
                <li key={item.id} className="rounded-lg border bg-card p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-snug">
                        {item.inbox_kind && (
                          <span className="mr-1 text-muted-foreground">{KIND_LABELS[item.inbox_kind]} ·</span>
                        )}
                        {item.title}
                      </p>
                      {(due || labels.length > 0) && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {due}
                          {labels.map((label) => (
                            <span key={label} className="ml-2 rounded bg-muted px-1.5 py-0.5">
                              {label}
                            </span>
                          ))}
                        </p>
                      )}
                      {source && (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline"
                        >
                          source: {sourceHost(source.url)}
                          <ExternalLink className="size-3" aria-hidden />
                        </a>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busyId === item.id}
                      onClick={() => onComplete(item)}
                    >
                      {item.inbox_kind === 'choose' ? 'Confirm' : 'Done'}
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
