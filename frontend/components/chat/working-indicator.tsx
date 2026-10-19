'use client';

import { cn } from '@/lib/utils';
import { useT } from '@/lib/i18n';
import { AgentAvatar } from '@/components/agents/agent-avatar';

/**
 * "PAI is typing": three soft dots that bounce in turn. Pure CSS (see
 * `.typing-dot` in globals.css); reduced motion leaves them still.
 */
export function WorkingIndicator({ className }: { className?: string }) {
  const t = useT();

  return (
    <div
      className={cn('flex h-4 items-center gap-1 text-brand', className)}
      role="status"
      aria-label={t('chat.agentWorking')}
    >
      {[0, 1, 2].map((i) => (
        <span key={i} className="typing-dot size-2 rounded-full bg-current" style={{ animationDelay: `${i * 0.16}s` }} />
      ))}
    </div>
  );
}

/** The typing dots inside a reply bubble, aligned with PAI's messages. */
export function TypingBubble() {
  return (
    <div className="mx-auto flex w-full max-w-3xl items-end gap-2.5 py-2">
      <AgentAvatar name="pai" size={32} className="mb-0.5" />
      <div className="rounded-3xl rounded-bl-md border bg-card px-4 py-3.5 shadow-soft">
        <WorkingIndicator />
      </div>
    </div>
  );
}
