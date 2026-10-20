import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';

/** The heading every student screen starts with: a quiet eyebrow, a heavy
 * title and one line of intro. The icon is a small mark beside the eyebrow,
 * not a coloured tile, so the words lead. */
export function PageHeader({ title, description, eyebrow, icon: Icon, tone = 'blue', action, className }: {
  title: string;
  description?: string;
  eyebrow?: string;
  icon?: LucideIcon;
  tone?: Tone;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn('mb-7 flex flex-wrap items-end justify-between gap-4 sm:mb-9', className)}>
      <div className="min-w-0 max-w-2xl">
        {eyebrow && (
          <p className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
            {Icon && <span aria-hidden className={cn('flex size-6 items-center justify-center rounded-md', toneClass[tone].soft, toneClass[tone].ink)}><Icon className="size-3.5" strokeWidth={2.4} /></span>}
            {eyebrow}
          </p>
        )}
        <h1 className="text-balance font-display text-[1.85rem] leading-[1.15] sm:text-[2.25rem]">{title}</h1>
        {description && <p className="mt-1.5 max-w-xl text-pretty text-sm leading-relaxed text-muted-foreground sm:text-[15px]">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 flex-wrap gap-2">{action}</div>}
    </header>
  );
}
