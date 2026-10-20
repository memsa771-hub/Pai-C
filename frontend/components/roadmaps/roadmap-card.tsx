'use client';
import { evidenceLabel, evidenceText } from '@/lib/evidence-text';
import { RoadmapFit } from './roadmap-fit';

import { Check, ExternalLink, Heart, MessageCircle, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatChip } from '@/components/pai';
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
  const ready = roadmap.generation_status === 'ready';
  const fitTone = !ready ? 'neutral' : roadmap.fit_level === 'strong' ? 'success' : roadmap.fit_level === 'partial' ? 'blue'
    : roadmap.fit_level === 'weak' || roadmap.fit_level === 'not_possible_yet' ? 'warning' : 'neutral';
  return <article className="flex min-w-0 flex-col rounded-3xl border bg-card p-5 shadow-card">
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <p className="text-xs font-semibold text-primary">{originLabel}</p>
        <h3 className="mt-1 break-words text-lg font-bold leading-snug">{roadmap.title || t('roadmapFit.routeTitle')}</h3>
        {routeDetail && <p className="mt-1 text-sm text-muted-foreground">{routeDetail}</p>}
      </div>
      <Button type="button" size="tap-icon" variant="ghost" disabled={busy} aria-pressed={roadmap.favorite}
        aria-label={roadmap.favorite ? t('counselorRoadmaps.removeFavorite') : t('counselorRoadmaps.favorite')}
        onClick={() => onAction('favorite', roadmap)}>
        <Heart className={roadmap.favorite ? 'fill-tone-rose text-tone-rose' : ''} />
      </Button>
    </div>
    <div className="mt-3 flex flex-wrap gap-2">
      <StatChip size="sm" tone={fitTone}>{ready
        ? t(`counselorRoadmaps.fit_${roadmap.fit_level || 'unconfirmed'}`)
        : t(`counselorRoadmaps.status_${roadmap.generation_status}`)}</StatChip>
      {roadmap.chosen_at && <StatChip size="sm" tone="success">{t('counselorRoadmaps.chosen')}</StatChip>}
      {roadmap.new && <StatChip size="sm" tone="sky">{t('counselorRoadmaps.new')}</StatChip>}
      {roadmap.generation_status === 'stale' && <StatChip size="sm" tone="warning">{t('counselorRoadmaps.needsReview')}</StatChip>}
      {roadmap.exploring && <StatChip size="sm" tone="blue">{t('counselorRoadmaps.exploring')}</StatChip>}
      {roadmap.total_cost?.status === 'verified' && roadmap.total_cost.amount != null &&
        <StatChip size="sm" tone="neutral">{roadmap.total_cost.currency} {roadmap.total_cost.amount} {evidenceText(roadmap.total_cost.basis)}</StatChip>}
      {roadmap.total_cost?.status !== 'verified' && <StatChip size="sm" tone="neutral" variant="outline">{t('counselorRoadmaps.costUnknown')}</StatChip>}
      {roadmap.time_to_start && <StatChip size="sm" tone="neutral">{t('counselorRoadmaps.start', { date: roadmap.time_to_start })}</StatChip>}
    </div>
    {typeof route.why_suggested === 'string' && <p className="mt-3 text-sm text-muted-foreground">{route.why_suggested}</p>}
    {Object.keys(roadmap.fit_dimensions || {}).length > 0 && <div className="mt-3 text-sm">
      <p className="font-semibold">{t('counselorRoadmaps.fitByArea')}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">{Object.entries(roadmap.fit_dimensions).map(([area, fit]) =>
        <span key={area} title={fit.reason || undefined} className="rounded-full border px-2.5 py-1 text-xs">{evidenceLabel(area)}: {evidenceText(fit.level)}</span>)}</div>
    </div>}
    <RoadmapFit roadmap={roadmap} compact />
    {!roadmap.lane && roadmap.gaps.length > 0 && <div className="mt-3 text-sm">
      <p className="font-semibold">{t('counselorRoadmaps.gaps')}</p>
      <ul className="mt-1 list-disc space-y-1 pl-5 text-muted-foreground">
        {roadmap.gaps.slice(0, 3).map((gap, index) => <li key={`${gap.field || 'gap'}-${index}`}>
          {gap.reason || (gap.field ? evidenceLabel(gap.field) : t('counselorRoadmaps.requirementToCheck'))}
          {gap.remediation?.action ? ` - ${gap.remediation.action}` : ''}</li>)}
      </ul>
    </div>}
    {roadmap.risks.length > 0 && <p className="mt-3 rounded-2xl bg-warning-soft px-3 py-2 text-sm text-warning-ink">{roadmap.risks.slice(0, 2).join(' · ')}</p>}
    {roadmap.stale_reason && <p className="mt-2 rounded-2xl bg-warning-soft px-3 py-2 text-sm text-warning-ink">{roadmap.stale_reason}</p>}
    {sources.length > 0 && <div className="mt-3 flex flex-wrap gap-3">{sources.map((source, index) =>
      <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noopener noreferrer"
        className="inline-flex min-h-8 items-center gap-1 text-sm font-semibold text-brand-ink underline-offset-4 hover:underline">
        {t('counselorRoadmaps.sourceNumber', { number: index + 1 })} <ExternalLink className="size-3.5" />
      </a>)}</div>}
    {roadmap.updated_at && <p className="mt-2 text-xs text-muted-foreground">{t('counselorRoadmaps.updated', {
      date: new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(roadmap.updated_at)) })}</p>}
    <div className="mt-auto flex flex-wrap gap-2 pt-4">
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at &&
        <Button type="button" size="tap" disabled={busy} onClick={() => onAction('choose', roadmap)}>
          <Check aria-hidden />{t('counselorRoadmaps.chooseConfirm')}</Button>}
      {['ready', 'needs_info', 'stale'].includes(roadmap.generation_status) &&
        <Button type="button" size="tap" variant="soft" disabled={busy} onClick={() => onAction('discuss', roadmap)}>
          <MessageCircle aria-hidden />{t('counselorRoadmaps.discuss')}</Button>}
      {onDetails && <Button type="button" size="tap" variant="outline" onClick={() => onDetails(roadmap)}>{t('counselorRoadmaps.details')}</Button>}
      {!roadmap.dismissed_at && <Button type="button" size="tap" variant="ghost" disabled={busy} onClick={() => onAction('exploring', roadmap)}>
        {roadmap.exploring ? t('counselorRoadmaps.stopExploring') : t('counselorRoadmaps.exploreLater')}</Button>}
      {roadmap.generation_status === 'ready' && !roadmap.chosen_at && !roadmap.dismissed_at &&
        <Button type="button" size="tap" variant="ghost" disabled={busy} onClick={() => onAction('rethink', roadmap)}>{t('counselorRoadmaps.rethink')}</Button>}
      {['failed', 'stale', 'needs_info'].includes(roadmap.generation_status) &&
        <Button type="button" size="tap" variant="outline" disabled={busy} onClick={() => onAction('retry', roadmap)}>{t('counselorRoadmaps.retry')}</Button>}
      {!roadmap.chosen_at && <Button type="button" size="tap" variant="ghost" disabled={busy}
        onClick={() => onAction(roadmap.dismissed_at ? 'restore' : 'dismiss', roadmap)}>
        {!roadmap.dismissed_at && <X aria-hidden />}
        {roadmap.dismissed_at ? t('counselorRoadmaps.restore') : t('counselorRoadmaps.dismiss')}
      </Button>}
    </div>
  </article>;
}
