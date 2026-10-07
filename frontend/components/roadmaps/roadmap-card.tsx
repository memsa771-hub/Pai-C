'use client';

import { ExternalLink, Heart, MessageCircle, X } from 'lucide-react';
import type { Roadmap } from '@/lib/roadmaps';
import { useT } from '../../lib/i18n';

export function RoadmapCard({ roadmap, busy, onAction, onDetails }: {
  roadmap: Roadmap;
  busy: boolean;
  onAction: (action: 'discuss' | 'favorite' | 'exploring' | 'dismiss' | 'restore' | 'choose' | 'rethink' | 'retry', roadmap: Roadmap) => void;
  onDetails?: (roadmap: Roadmap) => void;
}) {
  const t = useT();
  const sources = roadmap.sources.filter((item) => {
    try { return new URL(item.url).protocol === 'https:'; } catch { return false; }
  }).slice(0, 3);
  const route = roadmap.route || {};
  const routeDetail = [route.country, route.level, route.intake]
    .filter((value) => typeof value === 'string' && value).join(' · ');
  const originLabel = roadmap.origin === 'stated_goal' ? t('counselorRoadmaps.yourGoal')
    : roadmap.origin === 'student_added' ? t('counselorRoadmaps.addedByYou')
      : roadmap.origin === 'family_wish' ? t('counselorRoadmaps.familyWish')
        : t('counselorRoadmaps.alternative');
  return <article className="rounded-2xl border border-border bg-card p-4 shadow-sm">
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-primary">{originLabel}</p>
        <h3 className="mt-1 text-base font-semibold">{roadmap.title}</h3>
        {routeDetail && <p className="mt-1 text-xs text-muted-foreground">{routeDetail}</p>}
      </div>
      <button type="button" disabled={busy}
        aria-label={roadmap.favorite ? t('counselorRoadmaps.removeFavorite') : t('counselorRoadmaps.favorite')}
        onClick={() => onAction('favorite', roadmap)}
        className="rounded-lg p-2 hover:bg-muted disabled:opacity-50">
        <Heart className={`size-4 ${roadmap.favorite ? 'fill-rose-500 text-rose-500' : ''}`} />
      </button>
    </div>
    <div className="mt-3 flex flex-wrap gap-2 text-xs">
      <span className="rounded-full bg-muted px-2.5 py-1">{roadmap.generation_status === 'ready'
        ? t(`counselorRoadmaps.fit_${roadmap.fit_level || 'unconfirmed'}`)
        : t(`counselorRoadmaps.status_${roadmap.generation_status}`)}</span>
      {roadmap.chosen_at && <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary">{t('counselorRoadmaps.chosen')}</span>}
      {roadmap.new && <span className="rounded-full bg-sky-100 px-2.5 py-1 font-medium text-sky-800">{t('counselorRoadmaps.new')}</span>}
      {roadmap.generation_status === 'stale' && <span className="rounded-full bg-amber-100 px-2.5 py-1 text-amber-800">{t('counselorRoadmaps.needsReview')}</span>}
      {roadmap.exploring && <span className="rounded-full bg-primary/10 px-2.5 py-1 text-primary">{t('counselorRoadmaps.exploring')}</span>}
      {roadmap.total_cost?.status === 'verified' && roadmap.total_cost.amount != null &&
        <span className="rounded-full bg-muted px-2.5 py-1">{roadmap.total_cost.currency} {roadmap.total_cost.amount} {roadmap.total_cost.basis}</span>}
      {roadmap.total_cost?.status !== 'verified' &&
        <span className="rounded-full bg-muted px-2.5 py-1">{t('counselorRoadmaps.costUnknown')}</span>}
      {roadmap.time_to_start && <span className="rounded-full bg-muted px-2.5 py-1">{t('counselorRoadmaps.start', { date: roadmap.time_to_start })}</span>}
    </div>
    {typeof route.why_suggested === 'string' && <p className="mt-3 text-sm text-muted-foreground">{route.why_suggested}</p>}
    {Object.keys(roadmap.fit_dimensions || {}).length > 0 && <div className="mt-3 text-xs">
      <p className="font-medium">{t('counselorRoadmaps.fitByArea')}</p>
      <div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(roadmap.fit_dimensions).map(([area, fit]) =>
        <span key={area} title={fit.reason || undefined} className="rounded-full border px-2 py-1">{area}: {fit.level}</span>)}</div>
    </div>}
    {roadmap.gaps.length > 0 && <div className="mt-3 text-sm">
      <p className="font-medium">{t('counselorRoadmaps.gaps')}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
        {roadmap.gaps.slice(0, 3).map((gap, index) => <li key={`${gap.field || 'gap'}-${index}`}>
          {gap.reason || gap.field || t('counselorRoadmaps.requirementToCheck')}
          {gap.remediation?.action ? ` - ${gap.remediation.action}` : ''}</li>)}
      </ul>
    </div>}
    {roadmap.risks.length > 0 && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{roadmap.risks.slice(0, 2).join(' · ')}</p>}
    {roadmap.stale_reason && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">{roadmap.stale_reason}</p>}
    {sources.length > 0 && <div className="mt-3 flex flex-wrap gap-3">{sources.map((source, index) =>
      <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-xs text-primary underline">
        {t('counselorRoadmaps.sourceNumber', { number: index + 1 })} <ExternalLink className="size-3" />
      </a>)}</div>}
    {roadmap.updated_at && <p className="mt-2 text-[11px] text-muted-foreground">{t('counselorRoadmaps.updated', {
      date: new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(roadmap.updated_at)) })}</p>}
    <div className="mt-4 flex flex-wrap gap-2">
      {onDetails && <button type="button" onClick={() => onDetails(roadmap)}
        className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted">{t('counselorRoadmaps.details')}</button>}
      {['ready', 'needs_info', 'stale'].includes(roadmap.generation_status) &&
        <button type="button" disabled={busy} onClick={() => onAction('discuss', roadmap)}
          className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50">
          <MessageCircle className="size-3.5" /> {t('counselorRoadmaps.discuss')}</button>}
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at &&
        <button type="button" disabled={busy} onClick={() => onAction('choose', roadmap)}
          className="rounded-lg border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50">{t('counselorRoadmaps.chooseConfirm')}</button>}
      {!roadmap.dismissed_at && <button type="button" disabled={busy} onClick={() => onAction('exploring', roadmap)}
        className="rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50">
        {roadmap.exploring ? t('counselorRoadmaps.stopExploring') : t('counselorRoadmaps.exploreLater')}</button>}
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at &&
        <button type="button" disabled={busy} onClick={() => onAction('rethink', roadmap)}
          className="rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50">{t('counselorRoadmaps.rethink')}</button>}
      {['failed', 'stale'].includes(roadmap.generation_status) &&
        <button type="button" disabled={busy} onClick={() => onAction('retry', roadmap)}
          className="rounded-lg border px-3 py-1.5 text-xs hover:bg-muted disabled:opacity-50">{t('counselorRoadmaps.retry')}</button>}
      {!roadmap.chosen_at && <button type="button" disabled={busy}
        onClick={() => onAction(roadmap.dismissed_at ? 'restore' : 'dismiss', roadmap)}
        className="inline-flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50">
        {!roadmap.dismissed_at && <X className="size-3" />}
        {roadmap.dismissed_at ? t('counselorRoadmaps.restore') : t('counselorRoadmaps.dismiss')}
      </button>}
    </div>
  </article>;
}
