'use client';

import { useEffect, useState } from 'react';
import { Eye, MessageCircle, Scale, Sparkles, Target } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { CounselorMirrorDraft } from '@/lib/counselor-mirror';
import { QuadrantCard, type Quadrant } from '@/components/pai';

const QUADRANTS = [
  { key: 'you_say', icon: MessageCircle, tone: 'blue' },
  { key: 'life_shows', icon: Eye, tone: 'teal' },
  { key: 'pressure', icon: Scale, tone: 'amber' },
  { key: 'you_want', icon: Target, tone: 'violet' },
] as const;

/** An old Mirror in the conversation: PAI's picture as four quadrants, with
 * the dimensions and evidence one tap away. Read-only: the confirm, edit and
 * rating routes are gone (FOUR_FEATURES_SPEC 2.3); the Mirror page replaces
 * this card. */
export function CounselorMirrorCard({ refreshKey, onUpdated }: {
  refreshKey: string | number;
  onUpdated?: () => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState<CounselorMirrorDraft | null>(null);
  void onUpdated;

  useEffect(() => {
    let active = true;
    workspaceApi.getCounselorSummary().then((result) => { if (active) setDraft(result); }).catch(() => undefined);
    return () => { active = false; };
  }, [refreshKey]);

  if (draft?.type !== 'mirror' || !draft.mirror || draft.version === null) return null;
  const mirror = draft.mirror;

  const renderDimensions = () => (<div className="mt-3 divide-y rounded-2xl border px-4">
      {mirror.dimensions.map((dimension) => <details key={dimension.key} className="group py-3">
        <summary className="flex min-h-8 cursor-pointer list-none items-center justify-between gap-2 font-semibold break-words">
          {dimension.name}<span aria-hidden className="text-muted-foreground transition-transform group-open:rotate-90">›</span>
        </summary>
        <p className="mt-2 whitespace-pre-wrap break-words">{dimension.picture}</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">
          {dimension.unknown ? t('counselorMirror.unknown') : `${t('counselorMirror.evidence')}: ${dimension.evidence}`}
        </p>
      </details>)}
    </div>);

  const quadrants: Quadrant[] | null = mirror.core_picture ? QUADRANTS.map(({ key, icon, tone }) => ({
    key, icon, tone, label: t(`counselorMirror.${key}`), text: mirror.core_picture![key].text,
  })) : null;

  return <section className="max-h-[42dvh] min-w-0 overflow-y-auto rounded-3xl sm:max-h-[55dvh] border bg-card p-4 text-sm shadow-card sm:p-5" aria-label={t('counselorMirror.title')}>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="flex items-center gap-2.5 text-base font-bold">
        <span aria-hidden className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--hero-from)] to-[var(--hero-via)] text-white"><Sparkles className="size-[18px]" /></span>
        {t('counselorMirror.title')}
      </h3>
    </div>
    <p className="mt-3 whitespace-pre-wrap break-words text-[15px] leading-relaxed">{mirror.intro}</p>
    {quadrants && <QuadrantCard className="mt-3" quadrants={quadrants} />}
    {quadrants ? <details className="group mt-3">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-xl px-1 font-semibold text-brand-ink">{t('counselorMirror.details')}<span aria-hidden className="transition-transform group-open:rotate-90">›</span></summary>
      {renderDimensions()}
    </details> : renderDimensions()}
    {mirror.blockers.length > 0 && <div className="mt-4 rounded-2xl bg-warning-soft px-4 py-3 text-warning-ink">
      <h4 className="font-semibold">{t('counselorMirror.blockers')}</h4>
      <ul className="mt-1 list-disc space-y-1 pl-5 break-words">{mirror.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul>
    </div>}
    <h4 className="mt-4 font-semibold">{t('counselorMirror.opinion')}</h4>
    <p className="mt-1 whitespace-pre-wrap break-words">{mirror.opinion}</p>
    <p className="mt-3 whitespace-pre-wrap break-words font-medium">{mirror.question}</p>
  </section>;
}
