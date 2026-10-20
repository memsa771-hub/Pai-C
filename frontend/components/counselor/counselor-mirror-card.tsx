'use client';

import { useEffect, useRef, useState } from 'react';
import { Eye, MessageCircle, Scale, Sparkles, Target } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { CounselorMirrorDraft } from '@/lib/counselor-mirror';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { QuadrantCard, type Quadrant } from '@/components/pai';
import { FeltUnderstood } from '@/components/counselor/workspace/profile-parts';

const QUADRANTS = [
  { key: 'you_say', icon: MessageCircle, tone: 'blue' },
  { key: 'life_shows', icon: Eye, tone: 'teal' },
  { key: 'pressure', icon: Scale, tone: 'amber' },
  { key: 'you_want', icon: Target, tone: 'violet' },
] as const;

/** The Mirror in the conversation: PAI's picture as four quadrants, with
 * the dimensions and evidence one tap away. The student agrees or asks for
 * a change; a confirmed version may then be rated once (or skipped). */
export function CounselorMirrorCard({ refreshKey, onUpdated }: {
  refreshKey: string | number;
  onUpdated?: () => void;
}) {
  const t = useT();
  const [draft, setDraft] = useState<CounselorMirrorDraft | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [feedbackVersion, setFeedbackVersion] = useState<number | null>(null);
  const version = useRef<number | null>(null);
  const feedback = useRef<HTMLDivElement>(null);
  // After agreeing, bring the rating into view inside the scrolling card.
  useEffect(() => {
    if (feedbackVersion !== null) feedback.current?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  }, [feedbackVersion]);

  useEffect(() => {
    let active = true;
    workspaceApi.getCounselorSummary().then((result) => {
      if (!active) return;
      setDraft(result);
      if (version.current !== result.version) {
        version.current = result.version;
        setEditing(false); setText(''); setError(false); setFeedbackVersion(null);
      }
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [refreshKey]);

  if (draft?.type !== 'mirror' || !draft.mirror || draft.version === null) return null;
  const mirror = draft.mirror;
  const act = async (edit: boolean) => {
    setBusy(true); setError(false);
    try {
      if (edit) await workspaceApi.editCounselorMirror(draft.version!, text.trim());
      else await workspaceApi.confirmCounselorMirror(draft.version!);
      setDraft({ ...draft, status: edit ? 'needs_changes' : 'confirmed' });
      if (!edit) setFeedbackVersion(draft.version);
      setEditing(false); setText(''); onUpdated?.();
    } catch { setError(true); }
    finally { setBusy(false); }
  };

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
    {draft.status === 'confirmed' && <p role="status" className="mt-3 text-muted-foreground">{t('counselorMirror.confirmed')}</p>}
    {draft.status === 'needs_changes' && <p role="status" className="mt-3 text-muted-foreground">{t('counselorMirror.sent')}</p>}
    {error && <p role="alert" className="mt-2 font-medium text-danger-ink">{t('counselorMirror.error')}</p>}
    {feedbackVersion === draft.version && <div ref={feedback}><FeltUnderstood version={feedbackVersion}
      labels={{ legend: t('counselorMirror.understood'), certainty: `${t('counselorMirror.certaintyAfter')} (${t('counselorMirror.optional')})`,
        send: t('counselorMirror.sendFeedback'), skip: t('counselorMirror.skipFeedback') }}
      onSaved={() => onUpdated?.()} onSkip={() => { setFeedbackVersion(null); setError(false); }} /></div>}
    {draft.status === 'awaiting_confirmation' && <div className="mt-4">
      {editing ? <form onSubmit={(event) => { event.preventDefault(); void act(true); }}>
        <label className="block text-sm font-semibold">{t('counselorMirror.editHint')}
          <Textarea className="mt-2 min-h-24 rounded-xl" value={text} maxLength={8000} disabled={busy} onChange={(event) => setText(event.target.value)} />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="tap" type="submit" disabled={busy || !text.trim()}>{t('counselorMirror.saveEdits')}</Button>
          <Button size="tap" type="button" variant="ghost" disabled={busy} onClick={() => setEditing(false)}>{t('common.cancel')}</Button>
        </div>
      </form> : <div className="flex flex-wrap gap-2">
        <Button size="tap" type="button" disabled={busy} onClick={() => void act(false)}>{t('counselorMirror.confirm')}</Button>
        <Button size="tap" type="button" variant="outline" disabled={busy} onClick={() => setEditing(true)}>{t('counselorMirror.edit')}</Button>
      </div>}
    </div>}
  </section>;
}
