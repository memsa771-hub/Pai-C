'use client';

import { useMemo, useState, useCallback } from 'react';
import { MessageSquareMore, X } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import type { WorkspaceMessage } from '@/lib/types';
import { useT } from '@/lib/i18n';

interface QueuedMessage {
  queueId: string;
  content: string;
}

export function ThreadStatusBar({ channelName, messages = [] }: { channelName: string; messages?: WorkspaceMessage[] }) {
  const t = useT();
  const [cancelledQueueIds, setCancelledQueueIds] = useState<Set<string>>(new Set());

  // Extract queued messages from status messages with queue metadata
  const queuedMessages = useMemo(() => {
    // First pass: collect queue IDs that have been processed
    const processedIds = new Set<string>();
    for (const msg of messages) {
      if (msg.messageType !== 'status') continue;
      const meta = msg.metadata as Record<string, unknown> | undefined;
      if (meta?.queue_id && meta?.queue_status === 'processed') {
        processedIds.add(meta.queue_id as string);
      }
    }

    const queued: QueuedMessage[] = [];
    const seen = new Set<string>();
    // Walk messages in reverse to get latest state per queue_id
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.messageType !== 'status') continue;
      const meta = msg.metadata as Record<string, unknown> | undefined;
      if (!meta?.queue_id || !meta?.queued_message) continue;
      const qid = meta.queue_id as string;
      if (seen.has(qid) || cancelledQueueIds.has(qid) || processedIds.has(qid)) continue;
      seen.add(qid);
      queued.push({ queueId: qid, content: meta.queued_message as string });
    }
    return queued.reverse();
  }, [messages, cancelledQueueIds]);

  const handleCancelQueued = useCallback(async (queueId: string) => {
    setCancelledQueueIds((prev) => new Set(prev).add(queueId));
    try {
      await workspaceApi.cancelQueuedMessage(channelName, queueId);
    } catch {}
  }, [channelName]);

  if (!queuedMessages.length) return null;

  return (
    <div className="flex flex-col gap-0.5 px-1 py-1 text-[11px] text-muted-foreground">
      {queuedMessages.map((q) => (
        <div key={q.queueId} className="flex items-center gap-1.5 text-foreground/80">
          <MessageSquareMore className="size-3 shrink-0" />
          <span className="truncate">
            {t('threadStatus.queued', {
              content: q.content.length > 60 ? q.content.slice(0, 60) + '…' : q.content,
            })}
          </span>
          <button
            onClick={() => handleCancelQueued(q.queueId)}
            className="shrink-0 p-0.5 rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
            title={t('threadStatus.cancelQueuedMessage')}
          >
            <X className="size-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
