import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';

/** A rounded pill for a status or a short fact (stage, level, city, label). */
export function StatChip({ children, icon: Icon, tone, variant = 'soft', size = 'md', className, ...props }: {
  children: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone | 'neutral' | 'success' | 'warning' | 'danger';
  variant?: 'soft' | 'solid' | 'outline';
  size?: 'sm' | 'md';
  className?: string;
} & React.HTMLAttributes<HTMLSpanElement>) {
  const palette = tone === 'neutral' || !tone
    ? { soft: 'bg-muted text-foreground', solid: 'bg-foreground text-background', outline: 'border text-foreground' }
    : tone === 'success' ? { soft: 'bg-success-soft text-success-ink', solid: 'bg-success text-white dark:text-[#04201c]', outline: 'border border-success/50 text-success-ink' }
    : tone === 'warning' ? { soft: 'bg-warning-soft text-warning-ink', solid: 'bg-warning text-[#2b1700]', outline: 'border border-warning/50 text-warning-ink' }
    : tone === 'danger' ? { soft: 'bg-danger-soft text-danger-ink', solid: 'bg-danger text-white dark:text-[#2a0710]', outline: 'border border-danger/50 text-danger-ink' }
    : { soft: cn(toneClass[tone].soft, toneClass[tone].ink), solid: toneClass[tone].solid, outline: cn('border', toneClass[tone].ink) };
  return (
    <span
      className={cn('inline-flex max-w-full items-center gap-1.5 rounded-full font-medium',
        size === 'sm' ? 'px-2.5 py-0.5 text-xs' : 'px-3 py-1 text-sm', palette[variant], className)}
      {...props}
    >
      {Icon && <Icon aria-hidden className={size === 'sm' ? 'size-3.5 shrink-0' : 'size-4 shrink-0'} />}
      <span className="truncate">{children}</span>
    </span>
  );
}
