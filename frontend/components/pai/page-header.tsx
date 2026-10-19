import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';

/** The heading every student screen starts with: icon, title, one-line intro. */
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
    <header className={cn('mb-6 flex flex-wrap items-start justify-between gap-4 sm:mb-8', className)}>
      <div className="flex min-w-0 max-w-2xl items-start gap-4">
        {Icon && (
          <span aria-hidden className={cn('hidden size-12 shrink-0 items-center justify-center rounded-2xl sm:flex', toneClass[tone].soft, toneClass[tone].ink)}>
            <Icon className="size-6" />
          </span>
        )}
        <div className="min-w-0">
          {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-brand-ink">{eyebrow}</p>}
          <h1 className="text-balance text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
          {description && <p className="mt-2 text-pretty leading-relaxed text-muted-foreground">{description}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 flex-wrap gap-2">{action}</div>}
    </header>
  );
}
