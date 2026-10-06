'use client';

import { useEffect, useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import type { ApplicationCalendarEvent } from '@/lib/application-workspace';

const dayKey = (date: Date) => date.toISOString().slice(0, 10);

export function ApplicationCalendar({ onOpen }: { onOpen: (applicationId: string) => void }) {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [events, setEvents] = useState<ApplicationCalendarEvent[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const days = useMemo(() => {
    const first = new Date(Date.UTC(month.getFullYear(), month.getMonth(), 1));
    const start = new Date(first);
    start.setUTCDate(first.getUTCDate() - first.getUTCDay());
    return Array.from({ length: 42 }, (_, index) => {
      const date = new Date(start);
      date.setUTCDate(start.getUTCDate() + index);
      return date;
    });
  }, [month]);

  useEffect(() => {
    let live = true;
    setLoading(true); setError('');
    workspaceApi.getApplicationCalendar(dayKey(days[0]), dayKey(days[41]))
      .then((result) => { if (live) setEvents(result.events); })
      .catch(() => { if (live) setError('Calendar could not load.'); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [days]);

  const byDay = new Map<string, ApplicationCalendarEvent[]>();
  for (const event of events) byDay.set(event.date, [...(byDay.get(event.date) || []), event]);
  const monthLabel = new Intl.DateTimeFormat(undefined, { month: 'long', year: 'numeric' }).format(month);
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const weekdayNames = days.slice(0, 7).map((date) => new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(date));
  const monthEvents = events.filter((event) => event.date.slice(0, 7) === `${month.getFullYear()}-${String(month.getMonth() + 1).padStart(2, '0')}`);

  return <section className="rounded-2xl border bg-card p-4 shadow-sm sm:p-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="flex items-center gap-2 text-xl font-semibold"><CalendarDays className="size-5 text-primary" />Application calendar</h2><p className="mt-1 text-sm text-muted-foreground">Deadlines, requirement dates and the next scheduled PAI review.</p></div>
      <div className="flex items-center gap-2"><Button size="sm" variant="outline" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="size-4" /></Button><span className="min-w-36 text-center text-sm font-semibold">{monthLabel}</span><Button size="sm" variant="outline" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="size-4" /></Button></div>
    </div>
    {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
    {loading && <p className="mt-4 text-xs text-muted-foreground">Updating calendar…</p>}
    <div className="mt-5 overflow-x-auto"><div className="min-w-[630px]"><div className="grid grid-cols-7 text-center text-xs font-semibold text-muted-foreground">{weekdayNames.map((name, index) => <div className="py-2" key={index}>{name}</div>)}</div><div className="grid grid-cols-7 border-l border-t">{days.map((date) => { const key = dayKey(date); const inMonth = date.getUTCMonth() === month.getMonth(); return <div key={key} className={`min-h-25 border-b border-r p-1.5 ${inMonth ? '' : 'bg-muted/30 text-muted-foreground'}`}><div className={`mb-1 flex size-6 items-center justify-center rounded-full text-xs ${key === today ? 'bg-primary font-semibold text-primary-foreground' : ''}`}>{date.getUTCDate()}</div><div className="space-y-1">{(byDay.get(key) || []).map((event) => <button key={event.id} type="button" onClick={() => onOpen(event.application_id)} title={`${event.title} (${event.type})`} className={`w-full truncate rounded px-1.5 py-1 text-left text-[11px] font-medium hover:opacity-75 ${event.type === 'deadline' ? 'bg-rose-500/10 text-rose-700 dark:text-rose-300' : event.type === 'review' ? 'bg-violet-500/10 text-violet-700 dark:text-violet-300' : 'bg-primary/10 text-primary'}`}>{event.title}</button>)}</div></div>; })}</div></div></div>
    <div className="mt-6"><h3 className="text-sm font-semibold">This month · {monthEvents.length} events</h3>{monthEvents.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No dates added for this month.</p> : <div className="mt-2 space-y-2">{monthEvents.map((event) => <button key={event.id} type="button" onClick={() => onOpen(event.application_id)} className="flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm hover:bg-muted/40"><span>{event.title}<span className="ml-2 text-xs capitalize text-muted-foreground">{event.type}</span></span><time className="text-xs text-muted-foreground">{event.date}</time></button>)}</div>}</div>
  </section>;
}
