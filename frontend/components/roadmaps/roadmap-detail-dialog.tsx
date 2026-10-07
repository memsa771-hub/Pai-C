'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { RoadmapDetail } from '@/lib/roadmaps';
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/responsive-dialog';

function readable(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(readable).filter(Boolean).join(', ');
  if (typeof value === 'object') {
    const item = value as Record<string, unknown>;
    if (item.amount != null && item.currency) return `${item.currency} ${item.amount} ${String(item.basis || '').replaceAll('_', ' ')}`.trim();
    return Object.values(item).map(readable).filter(Boolean).join(', ');
  }
  return '';
}

export function RoadmapDetailDialog({ roadmapId, onClose, onReported }: {
  roadmapId: string | null;
  onClose: () => void;
  onReported?: () => void;
}) {
  const t = useT();
  const [detail, setDetail] = useState<RoadmapDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [reporting, setReporting] = useState(false);
  useEffect(() => {
    if (!roadmapId) { setDetail(null); return; }
    let active = true;
    setLoading(true); setError(''); setDetail(null);
    workspaceApi.getRoadmap(roadmapId).then((value) => { if (active) setDetail(value); })
      .catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : String(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [roadmapId]);

  const report = async () => {
    if (!detail?.evidence || reporting) return;
    setReporting(true);
    try {
      await workspaceApi.reportWrongRequirement(detail.evidence.id);
      toast.success(t('counselorRoadmaps.reportSuccess'));
      setDetail(await workspaceApi.getRoadmap(detail.id));
      onReported?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setReporting(false); }
  };

  const evidence = detail?.evidence;
  const claimGroups = evidence ? [
    { label: t('counselorRoadmaps.requirements'), values: evidence.rules },
    { label: t('counselorRoadmaps.cost'), values: Object.values(evidence.fees || {}) },
    { label: t('counselorRoadmaps.deadlines'), values: Object.values(evidence.deadlines || {}) },
  ] : [];
  return <Dialog open={!!roadmapId} onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="sm:max-w-3xl">
      <DialogHeader>
        <DialogTitle>{t('counselorRoadmaps.detailTitle')}</DialogTitle>
        <DialogDescription>{detail?.title || ''}</DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-5 py-3 text-sm">
        {loading && <p role="status">{t('counselorRoadmaps.loading')}</p>}
        {error && <p role="alert" className="text-destructive">{error}</p>}
        {detail && <>
          <section>
            <h3 className="font-semibold">{t('counselorRoadmaps.routeSummary')}</h3>
            <p className="mt-1 text-muted-foreground">{readable(detail.route.country)} {readable(detail.route.level)} {readable(detail.route.intake)}</p>
            {typeof detail.route.why_suggested === 'string' && <p className="mt-1">{detail.route.why_suggested}</p>}
            <p className="mt-2 font-medium">{evidence?.status === 'verified' ? t('counselorRoadmaps.verified') : t('counselorRoadmaps.unconfirmed')}</p>
            {evidence && Object.values(evidence.verification_checks || {}).filter((check) => !check.passed && check.reason)
              .map((check, index) => <p key={`${check.reason}-${index}`} className="text-amber-700">{check.reason}</p>)}
          </section>
          {Object.keys(detail.fit_dimensions || {}).length > 0 && <section>
            <h3 className="font-semibold">{t('counselorRoadmaps.fitByArea')}</h3>
            <ul className="mt-1 space-y-1">{Object.entries(detail.fit_dimensions).map(([name, item]) =>
              <li key={name}><strong>{name}:</strong> {item.level} — {item.reason}</li>)}</ul>
          </section>}
          {detail.gaps.length > 0 && <section>
            <h3 className="font-semibold">{t('counselorRoadmaps.gaps')}</h3>
            <ul className="mt-1 space-y-2">{detail.gaps.map((gap, index) =>
              <li key={`${gap.field || 'gap'}-${index}`}>{gap.reason || gap.status}
                {gap.remediation?.action && <span> — {gap.remediation.action}</span>}
                {gap.time_to_fix && <span> ({gap.time_to_fix})</span>}
              </li>)}</ul>
          </section>}
          {detail.steps.length > 0 && <section>
            <h3 className="font-semibold">{t('counselorRoadmaps.steps')}</h3>
            <ol className="mt-1 list-decimal space-y-1 pl-5">{detail.steps.map((step, index) =>
              <li key={index}>{readable(step.description || step.action || step.title)}
                {typeof step.owner_hint === 'string' && <span> ({step.owner_hint})</span>}</li>)}</ol>
          </section>}
          <section><h3 className="font-semibold">{t('counselorRoadmaps.cost')}</h3>
            <p className="mt-1">{detail.total_cost?.amount != null ? readable(detail.total_cost)
              : detail.total_cost?.reason || t('counselorRoadmaps.costUnknown')}</p></section>
          {detail.scholarships?.length > 0 && <section><h3 className="font-semibold">{t('counselorRoadmaps.scholarships')}</h3>
            <ul className="mt-1 space-y-2">{detail.scholarships.map((item, index) => <li key={`${item.source_url}-${index}`}>
              <p className="font-medium">{item.title}</p>
              <p>{[item.eligibility?.quote, item.amount?.quote, item.deadline?.quote].filter(Boolean).join(' · ')}</p>
              <p className="text-xs text-muted-foreground">{t('counselorRoadmaps.unconfirmed')}</p>
              <a href={item.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">{t('counselorRoadmaps.sources')}</a>
            </li>)}</ul>
          </section>}
          {claimGroups.map((group) => group.values.length > 0 && <section key={group.label}>
            <h3 className="font-semibold">{group.label}</h3>
            <ul className="mt-1 space-y-2">{group.values.map((claim, index) =>
              <li key={index} className="rounded-lg border p-2">
                <p>{claim.quote || readable(claim.value)}</p>
                <p className="mt-1 text-xs text-muted-foreground">{evidence?.status === 'verified'
                  ? t('counselorRoadmaps.verified') : t('counselorRoadmaps.unconfirmed')}</p>
                {claim.source_url && <a className="text-xs text-primary underline" href={claim.source_url} target="_blank" rel="noopener noreferrer">{t('counselorRoadmaps.sources')}</a>}
              </li>)}</ul>
          </section>)}
          {detail.sources.length > 0 && <section><h3 className="font-semibold">{t('counselorRoadmaps.sources')}</h3>
            <ul className="mt-1 space-y-1">{detail.sources.map((source, index) => <li key={`${source.url}-${index}`}>
              <a href={source.url} target="_blank" rel="noopener noreferrer" className="break-all text-primary underline">{source.url}</a>
              <span className="ml-2 text-xs text-muted-foreground">{t('counselorRoadmaps.checked', { date: new Date(source.checked_at).toLocaleDateString() })}</span>
            </li>)}</ul></section>}
          {detail.evidence_history.length > 0 && <section><h3 className="font-semibold">{t('counselorRoadmaps.history')}</h3>
            <ol className="mt-1 space-y-1">{detail.evidence_history.map((version) =>
              <li key={version.version}>v{version.version} — {version.status} — {new Date(version.checked_at).toLocaleDateString()}</li>)}</ol>
          </section>}
        </>}
      </DialogBody>
      <DialogFooter>
        {evidence && <button type="button" disabled={reporting} onClick={() => void report()}
          className="rounded-lg border px-4 py-2 text-sm disabled:opacity-50">{t('counselorRoadmaps.report')}</button>}
        <button type="button" onClick={onClose} className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground">{t('counselorRoadmaps.close')}</button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
