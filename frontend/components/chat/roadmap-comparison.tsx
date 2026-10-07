'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { RoadmapCard } from '@/components/roadmaps/roadmap-card';
import { RoadmapChoiceDialog } from '@/components/roadmaps/roadmap-choice-dialog';
import { RoadmapDetailDialog } from '@/components/roadmaps/roadmap-detail-dialog';
import { useLayout } from '@/components/layout/layout-context';
import { workspaceApi } from '@/lib/api';
import type { Roadmap } from '@/lib/roadmaps';

export function RoadmapComparison({ initial }: { initial: Roadmap[] }) {
  const [items, setItems] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [choice, setChoice] = useState<Roadmap | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const { openView } = useLayout();
  if (!items.length) return null;
  const action = async (kind: 'discuss' | 'favorite' | 'exploring' | 'dismiss' | 'restore' | 'choose' | 'rethink' | 'retry', roadmap: Roadmap) => {
    if (busy) return;
    if (kind === 'choose') { setChoice(roadmap); return; }
    setBusy(true);
    try {
      let updated: Roadmap;
      if (kind === 'discuss') {
        updated = await workspaceApi.focusRoadmap(roadmap.id);
        toast.success('PAI will use this route in your next message.');
      } else if (kind === 'rethink') {
        updated = await workspaceApi.rethinkRoadmap(roadmap.id);
        toast.success('PAI can revisit the direction with you.');
      } else if (kind === 'retry') {
        updated = await workspaceApi.retryRoadmap(roadmap.id);
      } else if (kind === 'favorite' || kind === 'exploring') {
        updated = await workspaceApi.setRoadmapFlag(roadmap.id, kind, !roadmap[kind]);
      } else {
        updated = await workspaceApi.setRoadmapDismissed(roadmap.id, kind === 'dismiss');
      }
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not update route'); }
    finally { setBusy(false); }
  };
  return <section aria-label="Route comparison" className="mt-4 rounded-xl border bg-muted/20 p-3">
    <div className="mb-3 flex items-center justify-between gap-2"><h4 className="text-sm font-semibold">Routes to consider</h4>
      <button type="button" onClick={() => openView('roadmaps')} className="text-xs text-primary underline">All roadmaps</button></div>
    <div className="grid gap-3 md:grid-cols-2">{items.map((item) => <RoadmapCard key={item.id} roadmap={item} busy={busy} onAction={action} onDetails={(roadmap) => setDetailId(roadmap.id)} />)}</div>
    <RoadmapChoiceDialog roadmap={choice} channel="chat" onClose={() => setChoice(null)}
      onChosen={(roadmap) => setItems((current) => current.map((item) => item.id === roadmap.id ? roadmap : item))} />
    <RoadmapDetailDialog roadmapId={detailId} onClose={() => setDetailId(null)} />
  </section>;
}
