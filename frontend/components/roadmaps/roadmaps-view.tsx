'use client';

import { useCallback, useEffect, useState } from 'react';
import { Map as MapIcon, Plus, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { EmptyState, Skeletons } from '@/components/pai';
import { toast } from 'sonner';
import { workspaceApi } from '@/lib/api';
import type { Roadmap } from '@/lib/roadmaps';
import type { StudentRequest } from '@/lib/roadmaps';
import { useT } from '@/lib/i18n';
import { useOperatorStatus } from '@/hooks/use-operator-status';
import { useLayout } from '@/components/layout/layout-context';
import { useWorkspace } from '@/lib/workspace-context';
import { PAI_PRIMARY_CONVERSATION_ID } from '@/lib/primary-conversation';
import { RoadmapCard } from './roadmap-card';
import { RoadmapChoiceDialog } from './roadmap-choice-dialog';
import { RoadmapDetailDialog } from './roadmap-detail-dialog';
import { StudentRequestCard } from './student-request-card';
import { Possibilities } from '@/components/counselor/possibilities';

type Filter = 'all' | 'favorites' | 'exploring' | 'dismissed';

/** `pathOnly` embeds the list inside a counselor page (no own heading or
 * scroll area, no free-form goals); `onChanged` lets the page refresh. */
export function RoadmapsView({ pathOnly = false, onChanged }: { pathOnly?: boolean; onChanged?: () => void }) {
  const [filter, setFilter] = useState<Filter>('all');
  const [roadmaps, setRoadmaps] = useState<Roadmap[]>([]);
  const [requests, setRequests] = useState<StudentRequest[]>([]);
  const [choice, setChoice] = useState<Roadmap | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [title, setTitle] = useState('');
  const [country, setCountry] = useState('');
  const [level, setLevel] = useState('');
  const [field, setField] = useState('');
  const [why, setWhy] = useState('');
  const { openView, openMobileDetail } = useLayout();
  const { setCurrentSessionId } = useWorkspace();
  const run = useOperatorStatus(true);
  const t = useT();
  const refresh = useCallback(async () => {
    try {
      const [cards, openRequests] = await Promise.all([
        workspaceApi.getRoadmaps(filter), workspaceApi.getStudentRequests(),
      ]);
      setRoadmaps(cards); setRequests(openRequests);
    }
    catch (error) { toast.error(error instanceof Error && error.message ? error.message : t('counselorRoadmaps.errorLoad')); }
    finally { setLoading(false); }
  }, [filter, t]);

  useEffect(() => { void refresh(); }, [refresh, run?.updatedAt]);
  useEffect(() => {
    if (!roadmaps.some((roadmap) => roadmap.generation_status === 'generating')) return;
    const timer = setInterval(() => { void refresh(); }, 15_000);
    return () => clearInterval(timer);
  }, [roadmaps, refresh]);

  const action = async (kind: 'discuss' | 'favorite' | 'exploring' | 'dismiss' | 'restore' | 'choose' | 'rethink' | 'retry', roadmap: Roadmap) => {
    if (busy) return;
    if (kind === 'choose') { setChoice(roadmap); return; }
    setBusy(true);
    try {
      if (kind === 'discuss') {
        await workspaceApi.focusRoadmap(roadmap.id);
        setCurrentSessionId(PAI_PRIMARY_CONVERSATION_ID);
        openView('threads');
        openMobileDetail();
      } else if (kind === 'rethink') {
        await workspaceApi.rethinkRoadmap(roadmap.id);
        await workspaceApi.focusRoadmap(roadmap.id);
        setCurrentSessionId(PAI_PRIMARY_CONVERSATION_ID);
        openView('threads'); openMobileDetail();
      } else if (kind === 'retry') {
        await workspaceApi.retryRoadmap(roadmap.id);
      } else if (kind === 'favorite' || kind === 'exploring') {
        await workspaceApi.setRoadmapFlag(roadmap.id, kind, !roadmap[kind]);
      } else {
        await workspaceApi.setRoadmapDismissed(roadmap.id, kind === 'dismiss');
      }
      await refresh();
    } catch (error) { toast.error(error instanceof Error && error.message ? error.message : t('counselorRoadmaps.errorUpdate')); }
    finally { setBusy(false); }
  };

  const addGoal = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      await workspaceApi.addCustomRoadmapGoal({ title: title.trim(),
        country: country.trim() || undefined, level: level.trim() || undefined,
        field: field.trim() || undefined, why: why.trim() || undefined });
      setTitle(''); setCountry(''); setLevel(''); setField(''); setWhy('');
      setAdding(false); setFilter('all');
      toast.success(t('counselorRoadmaps.researchRunning'));
      await refresh();
    } catch (error) { toast.error(error instanceof Error && error.message ? error.message : t('counselorRoadmaps.errorAdd')); }
    finally { setBusy(false); }
  };

  const refreshButton = <Button type="button" size="tap-icon" variant="outline" onClick={() => { setRefreshing(true); void refresh().finally(() => setRefreshing(false)); }}
    aria-label={t('counselorRoadmaps.refreshList')} aria-busy={refreshing}>
    <RefreshCw aria-hidden className={refreshing ? 'animate-spin' : ''} /></Button>;
  const header = pathOnly ? null : <div className="flex flex-wrap items-start justify-between gap-3">
    <div><h1 className="text-2xl font-bold">{t('counselorRoadmaps.viewTitle')}</h1><p className="mt-1 text-sm text-muted-foreground">{t('counselorRoadmaps.viewIntro')}</p></div>
    <div className="ms-auto flex gap-2">
      {refreshButton}
      <Button type="button" size="tap" onClick={() => setAdding(!adding)}><Plus aria-hidden /> {t('counselorRoadmaps.addGoal')}</Button>
    </div>
  </div>;
  const body = <>
      {header}
      {!pathOnly && <Possibilities refreshKey={roadmaps} onUpdated={() => void refresh()} />}
      {!pathOnly && adding && <form onSubmit={addGoal} className="mt-5 rounded-xl border bg-card p-4">
        <label htmlFor="roadmap-goal" className="text-sm font-medium">{t('counselorRoadmaps.customGoalTitle')}</label>
        <input id="roadmap-goal" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={240} required
          placeholder={t('counselorRoadmaps.customGoalExample')} className="mt-2 w-full rounded-lg border bg-background px-3 py-2 text-sm" />
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {([
            ['country', country, setCountry, 100],
            ['level', level, setLevel, 100],
            ['field', field, setField, 120],
            ['why', why, setWhy, 500],
          ] as const).map(([key, value, change, maxLength]) => <label key={key} className="text-xs font-medium">
            {t(`counselorRoadmaps.custom_${key}`)}
            <input value={value} onChange={(event) => change(event.target.value)} maxLength={maxLength}
              className="mt-1 block w-full rounded-lg border bg-background px-3 py-2 text-sm" />
          </label>)}
        </div>
        <div className="mt-3"><button type="submit" disabled={busy || title.trim().length < 2}
          className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">
          {t('counselorRoadmaps.customResearch')}</button></div>
        <p className="mt-2 text-xs text-muted-foreground">{t('counselorRoadmaps.customGoalHint')}</p>
      </form>}
      <div className={`flex flex-wrap items-center gap-2 ${pathOnly ? '' : 'mt-4'}`}>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('counselorRoadmaps.filtersLabel')}>{(['all', 'favorites', 'exploring', 'dismissed'] as const).map((option) => <button type="button" key={option} onClick={() => setFilter(option)} aria-pressed={filter === option}
          className={`min-h-11 rounded-full px-4 text-sm font-semibold transition-colors ${filter === option ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground hover:bg-accent'}`}>{t(`counselorRoadmaps.filter_${option}`)}</button>)}</div>
        {pathOnly && <div className="ms-auto">{refreshButton}</div>}
      </div>
      {run?.taskType === 'roadmap_research' && !['completed', 'failed', 'needs_user_action'].includes(run.status) &&
        <p role="status" className="mt-4 rounded-2xl bg-info-soft px-4 py-3 text-sm font-medium text-info-ink">{t('counselorRoadmaps.researchRunning')}</p>}
      {requests[0] && <div className="mt-4"><StudentRequestCard key={requests[0].id} request={requests[0]} onSent={() => void refresh()} /></div>}
      {loading ? <div className="mt-5"><Skeletons count={2} label={t('counselorRoadmaps.loadingList')} /></div> : roadmaps.length === 0 ?
        <EmptyState className="mt-5" icon={MapIcon} tone="amber" title={t('counselorRoadmaps.emptyTitle')} description={pathOnly ? t('counselorRoadmaps.pathFirstEmpty') : t('counselorRoadmaps.customGoalHint')} /> :
        <div className="mt-5 grid gap-5 md:grid-cols-2">{roadmaps.map((roadmap) => <RoadmapCard key={roadmap.id} roadmap={roadmap} busy={busy} onAction={action} onDetails={(item) => setDetailId(item.id)} />)}</div>}
      <RoadmapChoiceDialog roadmap={choice} channel="roadmaps" onClose={() => setChoice(null)} onChosen={() => { void refresh(); onChanged?.(); }} />
      <RoadmapDetailDialog roadmapId={detailId} onClose={() => setDetailId(null)} onReported={() => void refresh()} />
  </>;
  if (pathOnly) return <div>{body}</div>;
  return <div className="h-full overflow-y-auto bg-background">
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-8">{body}</div>
  </div>;
}
