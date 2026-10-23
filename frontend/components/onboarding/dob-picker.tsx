'use client';

import * as React from 'react';
import { ChevronDown, ChevronLeft, ChevronRight } from 'lucide-react';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { DEFAULT_LOCALE } from '@/lib/i18n/locales';
import { useT } from '@/lib/i18n';
import { cn } from '@/lib/utils';

type View = 'years' | 'months' | 'days';
const pad = (n: number) => String(n).padStart(2, '0');
const iso = (y: number, m: number, d: number) => `${y}-${pad(m + 1)}-${pad(d)}`;
function parse(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? { y: Number(match[1]), m: Number(match[2]) - 1, d: Number(match[3]) } : null;
}
function ageOn(today: Date, y: number, m: number, d: number) {
  let age = today.getFullYear() - y;
  if (today.getMonth() < m || (today.getMonth() === m && today.getDate() < d)) age--;
  return age;
}

/** Date of birth, chosen year → month → day (fast for a birthday, unlike
 * paging back month by month). Future dates are disabled; the value is ISO
 * YYYY-MM-DD, which the backend validates again. */
export function DobPicker({ id, field, value, onChange, invalid, describedBy }: {
  id?: string;
  /** Marks the trigger so a form can focus it on a validation error. */
  field?: string;
  value: string;
  onChange: (value: string) => void;
  invalid?: boolean;
  describedBy?: string;
}) {
  const t = useT();
  const today = React.useMemo(() => new Date(), []);
  const selected = parse(value);
  const [open, setOpen] = React.useState(false);
  const [view, setView] = React.useState<View>(selected ? 'days' : 'years');
  const [year, setYear] = React.useState(selected?.y ?? today.getFullYear() - 17);
  const [month, setMonth] = React.useState(selected?.m ?? 0);
  const yearsRef = React.useRef<HTMLDivElement>(null);

  const monthName = React.useMemo(() => new Intl.DateTimeFormat(DEFAULT_LOCALE, { month: 'long' }), []);
  const monthShort = React.useMemo(() => new Intl.DateTimeFormat(DEFAULT_LOCALE, { month: 'short' }), []);
  const weekday = React.useMemo(() => new Intl.DateTimeFormat(DEFAULT_LOCALE, { weekday: 'narrow' }), []);
  const long = React.useMemo(() => new Intl.DateTimeFormat(DEFAULT_LOCALE, { day: 'numeric', month: 'long', year: 'numeric' }), []);

  React.useEffect(() => {
    if (!open) return;
    setView(selected ? 'days' : 'years');
    if (selected) { setYear(selected.y); setMonth(selected.m); }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => {
    if (view !== 'years') return;
    // Keep the chosen (or a typical) year in view when the year grid opens.
    requestAnimationFrame(() => yearsRef.current?.querySelector<HTMLElement>('[data-current="true"]')?.scrollIntoView({ block: 'center' }));
  }, [view, open]);

  const years = Array.from({ length: 100 }, (_, i) => today.getFullYear() - i);
  const isFuture = (y: number, m: number, d: number) => new Date(y, m, d) > today;
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7; // Monday first
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(firstWeekday).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
  const shift = (delta: number) => {
    const next = new Date(year, month + delta, 1);
    if (next > today) return;
    setYear(next.getFullYear()); setMonth(next.getMonth());
  };
  const label = selected ? long.format(new Date(selected.y, selected.m, selected.d)) : '';
  const age = selected ? ageOn(today, selected.y, selected.m, selected.d) : null;
  const cell = 'flex items-center justify-center rounded-xl text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-30';

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button id={id} data-field={field} type="button" aria-invalid={invalid || undefined} aria-describedby={describedBy}
          className={cn('flex h-[52px] w-full items-center gap-3 overflow-clip rounded-[12px] border bg-white px-4 text-left leading-[1.45] transition-colors focus-visible:border-auth-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-auth-blue/20',
            invalid ? 'border-danger' : 'border-auth-line')}>
          <img alt="" src="/auth/calendar.svg" className="size-5 shrink-0" />
          <span className={cn('flex-1 truncate', selected ? 'text-[16px] text-auth-label' : 'text-[14px] text-auth-placeholder')}>
            {selected ? label : t('onboarding.date.placeholder')}
          </span>
          {age !== null && age >= 0 && (
            <span className="shrink-0 rounded-full bg-auth-panel px-2.5 py-0.5 text-xs font-semibold text-auth-muted">
              {t('onboarding.date.age', { age })}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" sideOffset={8}
        className="w-[min(330px,calc(100vw-2rem))] gap-3 rounded-2xl border border-auth-line bg-white p-3 font-display text-auth-ink shadow-[0_24px_60px_-20px_rgb(0_0_0/0.35)] ring-0">
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => shift(-1)} aria-label={t('onboarding.date.previous')} disabled={view !== 'days'}
            className="flex size-9 items-center justify-center rounded-lg hover:bg-auth-panel disabled:invisible">
            <ChevronLeft className="size-4" />
          </button>
          <button type="button" onClick={() => setView(view === 'months' ? 'days' : 'months')} aria-label={t('onboarding.date.chooseMonth')}
            className={cn('flex h-9 flex-1 items-center justify-center gap-1 rounded-lg text-sm font-semibold hover:bg-auth-panel', view === 'months' && 'bg-auth-panel')}>
            {monthName.format(new Date(year, month, 1))}<ChevronDown aria-hidden className="size-3.5 text-auth-muted" />
          </button>
          <button type="button" onClick={() => setView(view === 'years' ? 'days' : 'years')} aria-label={t('onboarding.date.chooseYear')}
            className={cn('flex h-9 flex-1 items-center justify-center gap-1 rounded-lg text-sm font-semibold hover:bg-auth-panel', view === 'years' && 'bg-auth-panel')}>
            {year}<ChevronDown aria-hidden className="size-3.5 text-auth-muted" />
          </button>
          <button type="button" onClick={() => shift(1)} aria-label={t('onboarding.date.nextMonth')}
            disabled={view !== 'days' || new Date(year, month + 1, 1) > today}
            className="flex size-9 items-center justify-center rounded-lg hover:bg-auth-panel disabled:invisible">
            <ChevronRight className="size-4" />
          </button>
        </div>

        {view === 'years' && (
          <div ref={yearsRef} role="listbox" aria-label={t('onboarding.date.chooseYear')} className="grid max-h-64 grid-cols-4 gap-1.5 overflow-y-auto pe-1">
            {years.map((y) => (
              <button key={y} type="button" role="option" aria-selected={y === year} data-current={y === year}
                onClick={() => { setYear(y); if (new Date(y, month, 1) > today) setMonth(today.getMonth()); setView('months'); }}
                className={cn(cell, 'h-11', y === year ? 'bg-auth-blue text-white' : 'hover:bg-auth-panel')}>
                {y}
              </button>
            ))}
          </div>
        )}

        {view === 'months' && (
          <div role="listbox" aria-label={t('onboarding.date.chooseMonth')} className="grid grid-cols-3 gap-1.5">
            {Array.from({ length: 12 }, (_, m) => (
              <button key={m} type="button" role="option" aria-selected={m === month} disabled={new Date(year, m, 1) > today}
                onClick={() => { setMonth(m); setView('days'); }}
                className={cn(cell, 'h-12', m === month ? 'bg-auth-blue text-white' : 'hover:bg-auth-panel')}>
                {monthShort.format(new Date(2000, m, 1))}
              </button>
            ))}
          </div>
        )}

        {view === 'days' && (
          <div>
            <div aria-hidden className="mb-1 grid grid-cols-7 text-center text-xs font-semibold text-auth-muted">
              {Array.from({ length: 7 }, (_, i) => <span key={i} className="py-1">{weekday.format(new Date(2024, 0, 1 + i))}</span>)}
            </div>
            <div className="grid grid-cols-7 gap-1">
              {cells.map((d, i) => d === null ? <span key={`e${i}`} /> : (() => {
                const on = selected?.y === year && selected?.m === month && selected?.d === d;
                const isToday = today.getFullYear() === year && today.getMonth() === month && today.getDate() === d;
                return (
                  <button key={d} type="button" disabled={isFuture(year, month, d)} aria-pressed={on}
                    aria-label={long.format(new Date(year, month, d))}
                    onClick={() => { onChange(iso(year, month, d)); setOpen(false); }}
                    className={cn(cell, 'aspect-square rounded-full',
                      on ? 'bg-auth-blue text-white' : 'hover:bg-auth-panel',
                      isToday && !on && 'ring-1 ring-auth-line')}>
                    {d}
                  </button>
                );
              })())}
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
