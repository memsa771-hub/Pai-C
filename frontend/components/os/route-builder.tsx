'use client';

import { useState, type FormEvent } from 'react';
import { ArrowDown, ArrowUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EligibilityCard } from '@/components/os/eligibility-card';
import {
  MAX_CHOICES,
  chipLabel,
  chipTone,
  type OsCard,
  type OsRoute,
  type OsRouteProgramme,
  type OsSuggestion,
  type Verdict,
} from '@/lib/os-self-serve';

interface RouteBuilderProps {
  routes: OsRoute[];
  route: string;
  onRoute: (key: string) => void;
  year: number;
  onYear: (year: number) => void;
  programmes: OsRouteProgramme[];
  choices: string[];
  onToggle: (ref: string) => void;
  onMove: (index: number, delta: number) => void;
  onStart: () => void;
  starting?: boolean;
  /** The programme whose card is open, with its card and swap suggestions (loaded by the page). */
  openRef?: string | null;
  openCard?: OsCard | null;
  openSuggestions?: OsSuggestion[];
  onOpen?: (ref: string | null) => void;
  onRequest: (request: { university: string; name: string; url: string }) => void;
  requestError?: string | null;
  requestSent?: string | null;
}

function routeName(r: OsRoute): string {
  return `${r.origin} → ${r.destination} · ${r.level}`;
}

/** The self-serve start (Slice 4 spec §5): route and intake, programmes with eligibility, ranked choices. */
export function RouteBuilder(props: RouteBuilderProps) {
  const { routes, route, onRoute, year, onYear, programmes, choices, onToggle, onMove, onStart, starting = false,
          openRef = null, openCard = null, openSuggestions = [], onOpen, onRequest, requestError, requestSent } = props;
  const [query, setQuery] = useState('');
  const [asking, setAsking] = useState(false);
  const q = query.trim().toLowerCase();
  const shown = q ? programmes.filter((p) => `${p.name} ${p.university}`.toLowerCase().includes(q)) : programmes;
  const byRef = Object.fromEntries(programmes.map((p) => [p.ref, p]));

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    onRequest({ university: String(f.get('university') ?? ''), name: String(f.get('name') ?? ''),
                url: String(f.get('url') ?? '') });
  };

  return (
    <div className="flex flex-col gap-6">
      <section aria-label="Route and intake" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">1. Where and when</h2>
        <select aria-label="Route" value={route} onChange={(e) => onRoute(e.target.value)}
                className="w-full rounded-md border bg-background px-2 py-2 text-sm">
          {routes.map((r) => <option key={r.key} value={r.key}>{routeName(r)}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm">
          Intake year
          <input type="number" aria-label="Intake year" value={year} min={2025} max={2100}
                 onChange={(e) => onYear(Number(e.target.value))}
                 className="w-24 rounded-md border bg-background px-2 py-1 text-sm" />
        </label>
      </section>

      <section aria-label="Programmes" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">2. Choose up to {MAX_CHOICES} programmes</h2>
        <input type="search" aria-label="Search programmes" placeholder="Search programmes" value={query}
               onChange={(e) => setQuery(e.target.value)}
               className="w-full rounded-md border bg-background px-2 py-2 text-sm" />
        {shown.length === 0 ? (
          <p className="px-1 py-4 text-sm text-muted-foreground">No programmes for this route and intake yet.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {shown.map((p) => {
              const verdict: Verdict = p.card && p.research_state === 'researched' ? p.card.verdict : 'unknown';
              const chosen = choices.includes(p.ref);
              return (
                <li key={p.ref} className="rounded-lg border bg-card p-3">
                  <div className="flex items-start justify-between gap-2">
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onOpen?.(openRef === p.ref ? null : p.ref)}>
                      <p className="break-words text-sm font-medium">{p.name}</p>
                      <p className="break-words text-xs text-muted-foreground">{p.university}</p>
                      <p className="mt-1 flex flex-wrap gap-1 text-xs">
                        <span className={`rounded px-1.5 py-0.5 ${chipTone(verdict)}`}>{chipLabel(p)}</span>
                        {p.requested_by_student && <span className="rounded bg-muted px-1.5 py-0.5">requested by a student</span>}
                      </p>
                    </button>
                    <Button size="sm" variant={chosen ? 'primary' : 'outline'}
                            disabled={!chosen && choices.length >= MAX_CHOICES} onClick={() => onToggle(p.ref)}>
                      {chosen ? 'Chosen' : 'Choose'}
                    </Button>
                  </div>
                  {openRef === p.ref && openCard && (
                    <div className="mt-2">
                      <EligibilityCard card={openCard} suggestions={openSuggestions} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <button type="button" className="self-start text-sm text-primary underline-offset-2 hover:underline"
                onClick={() => setAsking(!asking)}>
          Can&apos;t find it? Request a programme
        </button>
        {(asking || requestError || requestSent) && (
          <form onSubmit={submit} aria-label="Request a programme" className="flex flex-col gap-2 rounded-lg border p-3">
            <input name="university" required placeholder="University" aria-label="University"
                   className="w-full rounded-md border bg-background px-2 py-2 text-sm" />
            <input name="name" required placeholder="Programme name" aria-label="Programme name"
                   className="w-full rounded-md border bg-background px-2 py-2 text-sm" />
            <input name="url" type="url" required placeholder="https:// official programme page" aria-label="Programme page"
                   className="w-full rounded-md border bg-background px-2 py-2 text-sm" />
            {requestError && <p role="alert" className="break-words text-sm text-destructive">{requestError}</p>}
            {requestSent && <p className="break-words text-sm text-muted-foreground">{requestSent}</p>}
            <Button type="submit" size="sm" className="self-start">Request a programme</Button>
          </form>
        )}
      </section>

      <section aria-label="Your choices" className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">3. Your choices, best first</h2>
        {choices.length === 0 ? (
          <p className="text-sm text-muted-foreground">Choose at least one programme above.</p>
        ) : (
          <ol className="flex flex-col gap-1">
            {choices.map((ref, i) => (
              <li key={ref} className="flex items-center justify-between gap-2 rounded-md border px-2 py-1 text-sm">
                <span className="min-w-0 flex-1 break-words">{i + 1}. {byRef[ref]?.name ?? ref}</span>
                <span className="flex gap-1">
                  <Button size="icon" variant="ghost" aria-label="Move up" disabled={i === 0} onClick={() => onMove(i, -1)}>
                    <ArrowUp className="size-4" aria-hidden />
                  </Button>
                  <Button size="icon" variant="ghost" aria-label="Move down" disabled={i === choices.length - 1}
                          onClick={() => onMove(i, 1)}>
                    <ArrowDown className="size-4" aria-hidden />
                  </Button>
                </span>
              </li>
            ))}
          </ol>
        )}
        <Button onClick={onStart} disabled={starting || choices.length === 0}>
          {starting ? 'Starting…' : 'Start my plan'}
        </Button>
      </section>
    </div>
  );
}
