'use client';

import { ExternalLink, Heart, MessageCircle, X } from 'lucide-react';
import type { Roadmap } from '@/lib/roadmaps';

const fitLabel: Record<string, string> = {
  strong: 'Strong fit', partial: 'Partial fit', weak: 'Several gaps',
  not_possible_yet: 'Not possible yet', unconfirmed: 'Fit unconfirmed',
};

export function RoadmapCard({ roadmap, busy, onAction }: {
  roadmap: Roadmap;
  busy: boolean;
  onAction: (action: 'discuss' | 'favorite' | 'exploring' | 'dismiss' | 'restore' | 'choose' | 'rethink', roadmap: Roadmap) => void;
}) {
  const sources = roadmap.sources.filter((item) => {
    try { return new URL(item.url).protocol === 'https:'; } catch { return false; }
  }).slice(0, 3);
  const route = roadmap.route || {};
  const routeDetail = [route.country, route.level, route.intake].filter((value) => typeof value === 'string' && value).join(' · ');
  return <article className="rounded-2xl border border-border bg-card p-4 shadow-sm">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">
          {roadmap.origin === 'stated_goal' ? 'Your goal' : roadmap.origin === 'student_added' ? 'Added by you' : 'Alternative route'}
        </p>
        <h3 className="mt-1 text-base font-semibold">{roadmap.title}</h3>
        {routeDetail && <p className="mt-1 text-xs text-muted-foreground">{routeDetail}</p>}
      </div>
      <button type="button" disabled={busy} aria-label={roadmap.favorite ? 'Remove favorite' : 'Favorite route'}
        onClick={() => onAction('favorite', roadmap)} className="rounded-lg p-2 hover:bg-muted disabled:opacity-50">
        <Heart className={`size-4 ${roadmap.favorite ? 'fill-rose-500 text-rose-500' : ''}`} />
      </button>
    </div>
    <div className="mt-3 flex flex-wrap gap-2 text-xs">
      <span className="rounded-full bg-muted px-2.5 py-1">{roadmap.generation_status === 'ready' ? fitLabel[roadmap.fit_level || 'unconfirmed'] || 'Fit unconfirmed' : roadmap.generation_status.replace('_', ' ')}</span>
      {roadmap.chosen_at && <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary">Chosen</span>}
      {roadmap.new && <span className="rounded-full bg-sky-100 px-2.5 py-1 font-medium text-sky-800">New</span>}
      {roadmap.generation_status === 'stale' && <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-800">Needs fresh review</span>}
      {roadmap.exploring && <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary">Exploring</span>}
      {roadmap.total_cost?.amount != null && <span className="rounded-full bg-muted px-2.5 py-1">{roadmap.total_cost.currency || ''} {roadmap.total_cost.amount} {roadmap.total_cost.basis || ''}</span>}
      {roadmap.total_cost?.amount == null && <span className="rounded-full bg-muted px-2.5 py-1">Total cost unconfirmed</span>}
      {roadmap.time_to_start && <span className="rounded-full bg-muted px-2.5 py-1">Start: {roadmap.time_to_start}</span>}
    </div>
    {typeof route.why_suggested === 'string' && <p className="mt-3 text-sm text-muted-foreground">{route.why_suggested}</p>}
    {Object.keys(roadmap.fit_dimensions || {}).length > 0 && <div className="mt-3 text-xs">
      <p className="font-medium">Fit by area</p>
      <div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(roadmap.fit_dimensions).map(([area, fit]) =>
        <span key={area} title={fit.reason || undefined} className="rounded-full border px-2 py-1">{area}: {fit.level}</span>)}</div>
    </div>}
    {roadmap.gaps.length > 0 && <div className="mt-3 text-sm">
      <p className="font-medium">What needs attention</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
        {roadmap.gaps.slice(0, 3).map((gap, index) => <li key={`${gap.field || 'gap'}-${index}`}>{gap.reason || gap.field || 'Requirement to check'}{gap.remediation?.action ? ` — ${gap.remediation.action}` : ''}</li>)}
      </ul>
    </div>}
    {roadmap.risks.length > 0 && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{roadmap.risks.slice(0, 2).join(' · ')}</p>}
    {roadmap.stale_reason && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{roadmap.stale_reason}</p>}
    {sources.length > 0 && <div className="mt-3 flex flex-wrap gap-3">{sources.map((source, index) =>
      <a key={source.url} href={source.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-primary underline">
        Source {index + 1} <ExternalLink className="size-3" />
      </a>)}</div>}
    {roadmap.updated_at && <p className="mt-2 text-[11px] text-muted-foreground">Updated {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(roadmap.updated_at))}</p>}
    <div className="mt-4 flex flex-wrap gap-2">
      {['ready', 'needs_info', 'stale'].includes(roadmap.generation_status) ? <button type="button" disabled={busy}
        onClick={() => onAction('discuss', roadmap)} className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"><MessageCircle className="size-3.5" /> Discuss with PAI</button> : null}
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at && <button type="button" disabled={busy}
        onClick={() => onAction('choose', roadmap)} className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50">Choose route</button>}
      {!roadmap.dismissed_at && <button type="button" disabled={busy} onClick={() => onAction('exploring', roadmap)} className="rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50">{roadmap.exploring ? 'Stop exploring' : 'Explore later'}</button>}
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at && <button type="button" disabled={busy} onClick={() => onAction('rethink', roadmap)} className="rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50">Not yet — rethink</button>}
      {!roadmap.chosen_at && <button type="button" disabled={busy} onClick={() => onAction(roadmap.dismissed_at ? 'restore' : 'dismiss', roadmap)} className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50">{!roadmap.dismissed_at && <X className="size-3" />}{roadmap.dismissed_at ? 'Restore' : 'Dismiss'}</button>}
    </div>
  </article>;
}
