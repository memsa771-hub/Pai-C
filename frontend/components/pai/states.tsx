import type { LucideIcon } from 'lucide-react';
import { CloudOff, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';
import copy from './kit-copy.json';

/** Friendly, never blank: an icon, one line, and the next thing to do. */
export function EmptyState({ title, description, icon: Icon = Sparkles, tone = 'blue', action, className }: {
  title: string;
  description?: string;
  icon?: LucideIcon;
  tone?: Tone;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div role="status" className={cn('flex flex-col items-center rounded-2xl border-2 border-dashed bg-card/60 px-6 py-10 text-center', className)}>
      <span aria-hidden className={cn('mb-4 flex size-14 items-center justify-center rounded-2xl', toneClass[tone].soft, toneClass[tone].ink)}>
        <Icon className="size-7" />
      </span>
      <p className="text-balance font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-md text-pretty text-sm text-muted-foreground">{description}</p>}
      {action && <div className="mt-5 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ title = copy.errorTitle, description = copy.errorBody, onRetry, retryLabel = copy.retry, className }: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}) {
  return (
    <div role="alert" className={cn('flex flex-col items-center rounded-2xl border bg-card px-6 py-10 text-center shadow-soft', className)}>
      <span aria-hidden className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-warning-soft text-warning-ink">
        <CloudOff className="size-7" />
      </span>
      <p className="font-semibold">{title}</p>
      <p className="mt-1 max-w-md text-sm text-muted-foreground">{description}</p>
      {onRetry && <Button size="tap" variant="outline" className="mt-5" onClick={onRetry}>{retryLabel}</Button>}
    </div>
  );
}

/** Skeletons shaped like the content they stand in for. */
export function Skeletons({ variant = 'cards', count = 3, label = copy.loading }: {
  variant?: 'cards' | 'list' | 'profile' | 'chat';
  count?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-busy="true" aria-label={label}>
      <span className="sr-only">{label}</span>
      {variant === 'profile' ? (
        <div className="space-y-5">
          <div className="flex items-center gap-4 rounded-3xl border bg-card p-6">
            <Skeleton className="size-16 shrink-0 rounded-full" />
            <div className="flex-1 space-y-2"><Skeleton className="h-5 w-48" /><Skeleton className="h-4 w-64 max-w-full" /></div>
          </div>
          <Skeleton className="h-56 rounded-3xl" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">{Array.from({ length: 10 }, (_, i) => <Skeleton key={i} className="h-24 rounded-2xl" />)}</div>
        </div>
      ) : variant === 'chat' ? (
        <div className="space-y-4">
          {Array.from({ length: count }, (_, i) => (
            <div key={i} className={cn('flex gap-3', i % 2 && 'justify-end')}>
              {!(i % 2) && <Skeleton className="size-9 rounded-full" />}
              <Skeleton className={cn('h-16 rounded-2xl', i % 2 ? 'w-1/2' : 'w-2/3')} />
            </div>
          ))}
        </div>
      ) : variant === 'list' ? (
        <div className="space-y-3">{Array.from({ length: count }, (_, i) => <Skeleton key={i} className="h-16 rounded-2xl" />)}</div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: count }, (_, i) => (
            <div key={i} className="space-y-3 rounded-2xl border bg-card p-6">
              <Skeleton className="h-4 w-24" /><Skeleton className="h-6 w-3/4" /><Skeleton className="h-16 w-full" />
              <div className="flex gap-2 pt-2"><Skeleton className="h-11 w-24 rounded-xl" /><Skeleton className="h-11 w-20 rounded-xl" /></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
