'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowRight, Plane } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { formatDue, isNotice, isWaiting, type OsInboxItem } from '@/lib/os-inbox';
import { useT } from '@/lib/i18n';

/** The study abroad plan on the counsellor's Journey page (pai-merge hand test: the journey said "Stage B, 1 of 11"
 * while a full plan ran beside it, unmentioned). The plan's own next step and how many are open, in one card; the
 * inbox is one tap away. Nothing shows when the plan is off or not started. */
export function OsPlanCard() {
  return OS_UI_ENABLED ? <OsPlanCardShown /> : null;
}

function OsPlanCardShown() {
  const workspaceId = useParams<{ workspaceId: string }>()?.workspaceId;  // null outside a workspace route
  const t = useT();
  const [items, setItems] = useState<OsInboxItem[] | null>(null);
  useEffect(() => {
    let active = true;
    workspaceApi.getOsInbox().then((got) => { if (active) setItems(got); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const open = (items ?? []).filter((i) => !isWaiting(i) && !isNotice(i));
  if (!items || !workspaceId || (items.length === 0)) return null;
  const next = [...open].sort((a, b) => (a.due_at ?? '9').localeCompare(b.due_at ?? '9'))[0];
  return (
    <section aria-label={t('nav.studyAbroadPlan')} className="mb-6 rounded-[22px] bg-card p-5 shadow-card ring-1 ring-border/70">
      <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
        <Plane aria-hidden className="size-4 text-primary" />{t('nav.studyAbroadPlan')}
      </p>
      <p className="mt-2 text-sm">
        {open.length === 0 ? 'Nothing waits on you right now.' : `${open.length} ${open.length === 1 ? 'step waits' : 'steps wait'} on you.`}
      </p>
      {next && (
        <p className="mt-1 text-sm">
          <span className="font-semibold">Next: {next.title}</span>
          {formatDue(next) && <span className="text-muted-foreground"> · {formatDue(next)}</span>}
        </p>
      )}
      <Link href={`/${workspaceId}/os-inbox`} className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline">
        {t('nav.osInbox')}<ArrowRight aria-hidden className="size-4" />
      </Link>
    </section>
  );
}
