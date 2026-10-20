import type { LucideIcon } from 'lucide-react';
import { Check } from 'lucide-react';
import { cn } from '@/lib/utils';

export type TimelineState = 'done' | 'now' | 'next';
export type TimelineItem = {
  id: string;
  title: React.ReactNode;
  marker?: React.ReactNode;
  icon?: LucideIcon;
  state?: TimelineState;
  meta?: React.ReactNode;
  children?: React.ReactNode;
};

/** A vertical timeline. `state` drives done / now / next styling; the
 * current item gets a soft halo so it is findable at a glance. */
export function Timeline({ items, label, className }: { items: TimelineItem[]; label?: string; className?: string }) {
  return (
    <ol aria-label={label} className={cn('relative', className)}>
      {items.map((item, index) => {
        const state = item.state || 'next';
        const Icon = item.icon;
        const last = index === items.length - 1;
        return (
          <li key={item.id} aria-current={state === 'now' ? 'step' : undefined} className="relative flex gap-4 pb-4 last:pb-0">
            {!last && (
              <span aria-hidden className={cn('absolute left-5 top-11 -bottom-0 w-0.5 -translate-x-1/2 rounded-full',
                state === 'done' ? 'bg-foreground' : 'bg-border')} />
            )}
            <span
              aria-hidden
              className={cn(
                'relative z-10 flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-bold',
                state === 'done' && 'bg-foreground text-background',
                state === 'now' && 'bg-highlight text-highlight-ink ring-[1.5px] ring-highlight-ink shadow-lift',
                state === 'next' && 'border-2 border-dashed border-input bg-card text-muted-foreground',
              )}
            >
              {state === 'done' ? <Check className="size-5" /> : Icon ? <Icon className="size-5" /> : item.marker}
            </span>
            <div className={cn('min-w-0 flex-1 rounded-2xl p-4',
              state === 'now' ? 'border-[1.5px] border-foreground bg-card shadow-card' : 'border bg-card shadow-soft')}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0 font-semibold">{item.title}</div>
                {item.meta}
              </div>
              {item.children && <div className="mt-2">{item.children}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
