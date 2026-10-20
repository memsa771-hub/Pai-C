'use client';
import { Compass, Quote } from 'lucide-react';
import { StatChip, toneClass, toneFor, type Tone } from '@/components/pai';
import { cn } from '@/lib/utils';

/** The one path card: a colour accent per path (stable by id), the reason it
 * fits in the student's own words, and the actions the caller provides. */
export function PathCardView({ id, tone: given, title, whyLabel, why, quote, status, statusTone = 'neutral', actions, error, compact = false, headingLevel = 2 }: {
  id: string;
  /** From tonesByOrder; falls back to a hash of the id. */
  tone?: Tone;
  title: string;
  whyLabel: string;
  why: string;
  quote?: string;
  status?: string;
  statusTone?: 'neutral' | 'success' | 'warning' | 'blue';
  actions: React.ReactNode;
  error?: string | null;
  compact?: boolean;
  headingLevel?: 2 | 3;
}) {
  const tone = given || toneFor(id);
  const Heading = `h${headingLevel}` as const;
  return (
    <article className={cn('relative flex min-w-0 flex-col overflow-hidden rounded-3xl border bg-card shadow-card transition-shadow hover:shadow-lift', compact ? 'my-3 max-w-lg' : 'h-full')}>
      <div aria-hidden className={cn('h-1.5 w-full', toneClass[tone].bar)} />
      <div className={cn('flex flex-1 flex-col', compact ? 'p-4' : 'p-5 sm:p-6')}>
        <div className="flex items-start justify-between gap-3">
          <span aria-hidden className={cn('flex size-11 shrink-0 items-center justify-center rounded-2xl', toneClass[tone].soft, toneClass[tone].ink)}>
            <Compass className="size-5" />
          </span>
          {status && <StatChip size="sm" tone={statusTone}>{status}</StatChip>}
        </div>
        <Heading className={cn('mt-3 break-words font-bold tracking-tight', compact ? 'text-lg' : 'text-xl')}>{title}</Heading>
        <p className={'mt-3 text-xs font-semibold text-muted-foreground'}>{whyLabel}</p>
        <p className="mt-1 text-pretty text-sm leading-relaxed text-muted-foreground">{why}</p>
        {quote && (
          <blockquote className={cn('mt-4 flex gap-2 rounded-2xl px-4 py-3 text-sm', toneClass[tone].soft)}>
            <Quote aria-hidden className={cn('mt-0.5 size-4 shrink-0', toneClass[tone].ink)} />
            <span className="break-words">“{quote}”</span>
          </blockquote>
        )}
        {error && <p role="alert" className="mt-3 text-sm font-medium text-danger-ink">{error}</p>}
        <div className="mt-auto flex flex-wrap gap-2 pt-5">{actions}</div>
      </div>
    </article>
  );
}
