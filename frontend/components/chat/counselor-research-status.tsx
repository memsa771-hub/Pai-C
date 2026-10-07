'use client';

import { useEffect, useState } from 'react';
import { useOperatorStatus } from '@/hooks/use-operator-status';
import { useLayout } from '@/components/layout/layout-context';
import { useT } from '@/lib/i18n';

export function CounselorResearchStatus() {
  const t = useT();
  const run = useOperatorStatus(true);
  const { openView } = useLayout();
  const [now, setNow] = useState(Date.now());
  const active = run?.taskType === 'roadmap_research' &&
    !['completed', 'needs_user_action', 'failed'].includes(run.status);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  if (run?.taskType !== 'roadmap_research' || (!active && run.status !== 'failed')) return null;
  const seconds = run.createdAt ? Math.max(0, Math.floor((now - Date.parse(run.createdAt)) / 1000)) : 0;
  return <div role="status" aria-live="polite" className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/30 px-3 py-2 text-xs">
    <span>{active ? `${t('counselorRoadmaps.researchRunning')} ${seconds}s`
      : t('counselorRoadmaps.researchFailed')}</span>
    <button type="button" onClick={() => openView('roadmaps')} className="font-medium text-primary underline">
      {t('counselorRoadmaps.viewRoadmaps')}
    </button>
  </div>;
}
