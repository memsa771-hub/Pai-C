'use client';

import { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
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

type Filter = 'all' | 'favorites' | 'exploring' | 'dismissed';

export function RoadmapsView() {
  const [filter, setFilter] = useState<Filter>('all');
  const [roadmaps, setRoadmaps] = useState<Roadmap[]>([]);
  const [requests, setRequests] = useState<StudentRequest[]>([]);
  const [choice, setChoice] = useState<Roadmap | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [adding, setAdding] = useState(false);
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
    catch (error) { toast.error(error instanceof Error ? error.message : 'Could not load roadmaps'); }
    finally { setLoading(false); }
  }, [filter]);

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
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not update roadmap'); }
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
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not add goal'); }
    finally { setBusy(false); }
  };

  return <div className="h-full overflow-y-auto bg-background">
    <div className="mx-auto max-w-5xl px-4 py-6 sm:px-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-2xl font-semibold">Roadmaps</h1><p className="mt-1 text-sm text-muted-foreground">Compare possible directions, discuss them with PAI, and choose when you are ready.</p></div>
        <div className="flex gap-2"><button type="button" onClick={() => void refresh()} aria-label="Refresh roadmaps" className="rounded-lg border p-2 hover:bg-muted"><RefreshCw className="size-4" /></button>
          <button type="button" onClick={() => setAdding(!adding)} className="inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"><Plus className="size-4" /> Add goal</button></div>
      </div>
      {adding && <form onSubmit={addGoal} className="mt-5 rounded-xl border bg-card p-4">
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
      <div className="mt-6 flex flex-wrap gap-2" aria-label="Roadmap filters">{(['all', 'favorites', 'exploring', 'dismissed'] as const).map((option) => <button type="button" key={option} onClick={() => setFilter(option)}
        className={`rounded-full px-3 py-1.5 text-xs capitalize ${filter === option ? 'bg-primary text-primary-foreground' : 'border hover:bg-muted'}`}>{option}</button>)}</div>
      {run?.taskType === 'roadmap_research' && !['completed', 'failed', 'needs_user_action'].includes(run.status) &&
        <p role="status" className="mt-4 rounded-lg border bg-muted/30 p-3 text-sm">{t('counselorRoadmaps.researchRunning')}</p>}
      {requests[0] && <div className="mt-4"><StudentRequestCard key={requests[0].id} request={requests[0]} onSent={() => void refresh()} /></div>}
      {loading ? <p className="mt-8 text-sm text-muted-foreground">Loading roadmaps…</p> : roadmaps.length === 0 ?
        <div className="mt-8 rounded-2xl border border-dashed p-8 text-center"><p className="font-medium">No roadmaps here yet</p><p className="mt-2 text-sm text-muted-foreground">Tell PAI about your goals and complete your profile foundation, or add a goal to research.</p></div> :
        <div className="mt-5 grid gap-4 md:grid-cols-2">{roadmaps.map((roadmap) => <RoadmapCard key={roadmap.id} roadmap={roadmap} busy={busy} onAction={action} onDetails={(item) => setDetailId(item.id)} />)}</div>}
      <RoadmapChoiceDialog roadmap={choice} channel="roadmaps" onClose={() => setChoice(null)} onChosen={() => void refresh()} />
      <RoadmapDetailDialog roadmapId={detailId} onClose={() => setDetailId(null)} onReported={() => void refresh()} />
    </div>
  </div>;
}
