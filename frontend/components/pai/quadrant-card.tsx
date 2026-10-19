import type { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { toneClass, type Tone } from './tone';

export type Quadrant = { key: string; label: string; text: string; icon: LucideIcon; tone: Tone; note?: React.ReactNode };

/** Four coloured quadrants (the Mirror). Each quadrant is one sentence. */
export function QuadrantCard({ quadrants, className }: { quadrants: Quadrant[]; className?: string }) {
  return (
    <dl className={cn('grid gap-3 sm:grid-cols-2', className)}>
      {quadrants.map(({ key, label, text, icon: Icon, tone, note }) => (
        <div key={key} className={cn('flex min-w-0 flex-col gap-2 rounded-2xl p-4 sm:p-5', toneClass[tone].soft)}>
          <dt className={cn('flex items-center gap-2 text-xs font-bold uppercase tracking-wider', toneClass[tone].ink)}>
            <span aria-hidden className="flex size-7 items-center justify-center rounded-lg bg-card/80">
              <Icon className="size-4" />
            </span>
            {label}
          </dt>
          <dd className="text-pretty break-words text-base font-medium leading-relaxed text-foreground">{text}</dd>
          {note && <dd className="text-xs text-muted-foreground">{note}</dd>}
        </div>
      ))}
    </dl>
  );
}
