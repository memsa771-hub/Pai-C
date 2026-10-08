'use client';

import { useEffect, useRef, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { CounselorMirrorDraft } from '@/lib/counselor-mirror';

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
  const version = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    workspaceApi.getCounselorSummary().then((result) => {
      if (!active) return;
      setDraft(result);
      if (version.current !== result.version) {
        version.current = result.version;
        setEditing(false); setText(''); setError(false);
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
      setEditing(false); setText(''); onUpdated?.();
    } catch { setError(true); }
    finally { setBusy(false); }
  };

  return <section className="max-h-[55dvh] min-w-0 overflow-y-auto rounded-xl border bg-card p-3 text-sm" aria-label={t('counselorMirror.title')}>
    <h3 className="font-semibold">{t('counselorMirror.title')}</h3>
    <p className="mt-2 whitespace-pre-wrap break-words">{mirror.intro}</p>
    <div className="mt-3 divide-y rounded-lg border px-3">
      {mirror.dimensions.map((dimension) => <details key={dimension.key} className="py-2">
        <summary className="cursor-pointer font-medium break-words">{dimension.name}</summary>
        <p className="mt-2 whitespace-pre-wrap break-words">{dimension.picture}</p>
        <p className="mt-1 whitespace-pre-wrap break-words text-xs text-muted-foreground">
          {dimension.unknown ? t('counselorMirror.unknown') : `${t('counselorMirror.evidence')}: ${dimension.evidence}`}
        </p>
      </details>)}
    </div>
    <h4 className="mt-3 font-medium">{t('counselorMirror.blockers')}</h4>
    <ul className="mt-1 list-disc space-y-1 pl-5 break-words">{mirror.blockers.map((blocker, index) => <li key={index}>{blocker}</li>)}</ul>
    <h4 className="mt-3 font-medium">{t('counselorMirror.opinion')}</h4>
    <p className="mt-1 whitespace-pre-wrap break-words">{mirror.opinion}</p>
    <p className="mt-2 whitespace-pre-wrap break-words">{mirror.question}</p>
    {draft.status === 'confirmed' && <p role="status" className="mt-3 text-muted-foreground">{t('counselorMirror.confirmed')}</p>}
    {draft.status === 'needs_changes' && <p role="status" className="mt-3 text-muted-foreground">{t('counselorMirror.sent')}</p>}
    {error && <p role="alert" className="mt-2 text-destructive">{t('counselorMirror.error')}</p>}
    {draft.status === 'awaiting_confirmation' && <div className="mt-3">
      {editing ? <form onSubmit={(event) => { event.preventDefault(); void act(true); }}>
        <label className="block text-xs font-medium">{t('counselorMirror.editHint')}
          <textarea className="mt-2 min-h-24 w-full rounded-lg border bg-background p-2 text-sm"
            value={text} maxLength={8000} disabled={busy} onChange={(event) => setText(event.target.value)} />
        </label>
        <div className="mt-2 flex flex-wrap gap-2">
          <button disabled={busy || !text.trim()} className="rounded-lg bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">{t('counselorMirror.saveEdits')}</button>
          <button type="button" disabled={busy} onClick={() => setEditing(false)} className="rounded-lg border px-3 py-2">{t('common.cancel')}</button>
        </div>
      </form> : <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => void act(false)} className="rounded-lg bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">{t('counselorMirror.confirm')}</button>
        <button type="button" disabled={busy} onClick={() => setEditing(true)} className="rounded-lg border px-3 py-2">{t('counselorMirror.edit')}</button>
      </div>}
    </div>}
  </section>;
}
