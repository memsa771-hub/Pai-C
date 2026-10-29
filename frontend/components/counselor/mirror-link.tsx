'use client';
import { ArrowRight, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { MirrorHeader } from '@/lib/mirror';
import { openWorkspaceView } from './workspace-link';
import copy from './workspace/copy.json';

/** The chat `counselor_mirror` card: who the Mirror is about and a way to it.
 * The Mirror itself lives on its page; the chat only points there. */
export function MirrorLink({ header }: { header?: MirrorHeader | null }) {
  const line = [header?.name, header?.education_line?.text].filter(Boolean).join(' · ');
  return (
    <div className="mt-3 flex min-w-0 flex-wrap items-center gap-3 rounded-2xl bg-card p-3 shadow-card ring-1 ring-border/70">
      <span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft text-primary">
        <Sparkles className="size-5" />
      </span>
      <span className="min-w-0 flex-1 basis-48">
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-primary">{copy.mirror.title}</span>
        {line && <span className="block text-pretty text-sm font-semibold">{line}</span>}
      </span>
      <Button size="tap" variant="soft" onClick={() => openWorkspaceView('mirror')}>
        {copy.mirror.chatOpen}<ArrowRight aria-hidden />
      </Button>
    </div>
  );
}
