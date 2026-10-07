'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { DecisionRecord, Roadmap } from '@/lib/roadmaps';
import {
  Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/responsive-dialog';

export function RoadmapChoiceDialog({ roadmap, channel, onClose, onChosen }: {
  roadmap: Roadmap | null;
  channel: 'chat' | 'roadmaps';
  onClose: () => void;
  onChosen: (roadmap: Roadmap) => void;
}) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [chosen, setChosen] = useState(false);
  const [decision, setDecision] = useState<DecisionRecord | null>(null);
  useEffect(() => { setError(''); setChosen(false); setDecision(null); }, [roadmap?.id]);

  const confirm = async () => {
    if (!roadmap || busy) return;
    setBusy(true);
    setError('');
    try {
      const token = await workspaceApi.getRoadmapChoiceToken(roadmap.id);
      const selected = await workspaceApi.chooseRoadmap(roadmap.id, token, channel);
      setChosen(true);
      onChosen(selected);
      try { setDecision(await workspaceApi.getCurrentDecision()); }
      catch { /* The choice succeeded; a summary read can be retried later. */ }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  const gaps = (roadmap?.gaps || []).filter((gap) => gap.status !== 'met');
  return <Dialog open={!!roadmap} onOpenChange={(open) => { if (!open && !busy) onClose(); }}>
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{chosen ? t('counselorRoadmaps.chosen') : t('counselorRoadmaps.chooseTitle')}</DialogTitle>
        <DialogDescription>{roadmap?.title}</DialogDescription>
      </DialogHeader>
      <DialogBody className="space-y-4 py-3 text-sm">
        {chosen ? <section role="status"><p>{t('counselorRoadmaps.decisionSaved')}</p>
          {decision?.real_objective && <p className="mt-2">{decision.real_objective}</p>}
        </section> : <>
          <p>{t('counselorRoadmaps.chooseIntro')}</p>
          <section aria-label={t('counselorRoadmaps.acceptedGaps')}>
            <h3 className="font-semibold">{t('counselorRoadmaps.acceptedGaps')}</h3>
            {gaps.length ? <ul className="mt-1 list-disc space-y-1 pl-5">{gaps.map((gap, index) =>
              <li key={`${gap.field || 'gap'}-${index}`}>{gap.reason || gap.field}</li>)}</ul>
              : <p className="mt-1 text-muted-foreground">{t('counselorRoadmaps.noGaps')}</p>}
          </section>
          <section aria-label={t('counselorRoadmaps.acceptedRisks')}>
            <h3 className="font-semibold">{t('counselorRoadmaps.acceptedRisks')}</h3>
            {roadmap?.risks.length ? <ul className="mt-1 list-disc space-y-1 pl-5">{roadmap.risks.map((risk, index) =>
              <li key={`${risk}-${index}`}>{risk}</li>)}</ul>
              : <p className="mt-1 text-muted-foreground">{t('counselorRoadmaps.noRisks')}</p>}
          </section>
        </>}
        {error && <p role="alert" className="text-destructive">{error}</p>}
      </DialogBody>
      <DialogFooter>
        <button type="button" onClick={onClose} disabled={busy} className="rounded-lg border px-4 py-2 text-sm">
          {chosen ? t('counselorRoadmaps.close') : t('common.cancel')}
        </button>
        {!chosen && <button type="button" onClick={() => void confirm()} disabled={busy}
          className="rounded-lg bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50">
          {t('counselorRoadmaps.chooseConfirm')}
        </button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
