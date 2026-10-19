import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';

/** The one card surface. `variant` changes emphasis, never the structure. */
export function SectionCard({ title, description, icon: Icon, tone = 'blue', action, variant = 'default',
  as: Tag = 'section', headingLevel = 2, className, bodyClassName, children, ...props }: {
  title?: React.ReactNode;
  description?: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  action?: React.ReactNode;
  variant?: 'default' | 'tinted' | 'dashed' | 'plain';
  as?: 'section' | 'article' | 'div';
  headingLevel?: 2 | 3;
  className?: string;
  bodyClassName?: string;
  children?: React.ReactNode;
} & Omit<React.HTMLAttributes<HTMLElement>, 'title'>) {
  const Heading = `h${headingLevel}` as const;
  return (
    <Tag
      className={cn(
        'min-w-0 rounded-2xl p-5 sm:p-6',
        variant === 'default' && 'border bg-card text-card-foreground shadow-card',
        variant === 'tinted' && cn('border border-transparent', toneClass[tone].soft),
        variant === 'dashed' && 'border-2 border-dashed bg-card/50',
        variant === 'plain' && 'bg-transparent p-0 sm:p-0',
        className,
      )}
      {...props}
    >
      {(title || action) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-[min(100%,14rem)] flex-1 items-center gap-3">
            {Icon && (
              <span aria-hidden className={cn('flex size-9 shrink-0 items-center justify-center rounded-xl',
                variant === 'tinted' ? 'bg-card/70' : toneClass[tone].soft, toneClass[tone].ink)}>
                <Icon className="size-[18px]" />
              </span>
            )}
            <div className="min-w-0">
              {title && <Heading className="text-base font-semibold leading-snug sm:text-lg">{title}</Heading>}
              {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
            </div>
          </div>
          {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </Tag>
  );
}
