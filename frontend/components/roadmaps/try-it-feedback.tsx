'use client';
import { useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { Roadmap } from '@/lib/roadmaps';
import { PAI_PRIMARY_CONVERSATION_ID } from '@/lib/primary-conversation';

export function TryItFeedback({ roadmap }: { roadmap: Roadmap }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [feeling, setFeeling] = useState<'more' | 'okay' | 'notForMe' | ''>('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(false);
  const trial = roadmap.try_it;
  if (!trial) return null;
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!feeling || busy) return;
    setBusy(true); setError(false);
    try {
      await workspaceApi.sendEvent({ type: 'workspace.message.posted',
        target: `channel/${PAI_PRIMARY_CONVERSATION_ID}`,
        payload: { content: t('tryIt.message', { title: roadmap.title, feeling: t(`tryIt.${feeling}`), note: note.trim() }), message_type: 'chat' },
        metadata: { target_agents: ['pai'], try_it_roadmap_id: roadmap.id }, visibility: 'channel' });
      setSent(true); setOpen(false);
    } catch { setError(true); }
    finally { setBusy(false); }
  };
  return <section className="min-w-0 space-y-2 rounded-lg border p-3">
    <h4 className="font-medium">{t('tryIt.title')}</h4>
    <p>{t(`tryIt.${trial.kind}`)}</p><p>{trial.what}</p><p className="text-muted-foreground">{trial.time_needed}</p>
    {!!trial.questions.length && <ol className="list-inside list-decimal">{trial.questions.map((question, index) => <li key={index}>{question}</li>)}</ol>}
    {sent ? <p role="status">{t('tryIt.sent')}</p> : <button type="button" onClick={() => setOpen(true)} className="rounded border px-3 py-2">{t('tryIt.tried')}</button>}
    {open && <form onSubmit={submit} className="space-y-2">
      <fieldset disabled={busy}><legend>{t('tryIt.feeling')}</legend>
        <div className="flex flex-wrap gap-2">{(['more', 'okay', 'notForMe'] as const).map(value =>
          <button type="button" key={value} aria-pressed={feeling === value} onClick={() => setFeeling(value)}
            className="rounded border px-3 py-2 aria-pressed:bg-muted">{t(`tryIt.${value}`)}</button>)}</div>
      </fieldset>
      <label className="block">{t('tryIt.note')}<textarea value={note} disabled={busy} onChange={event => setNote(event.target.value)}
        className="mt-1 w-full rounded border bg-background p-2" /></label>
      <button type="submit" disabled={busy || !feeling} className="rounded border px-3 py-2">{t('tryIt.send')}</button>
      <button type="button" disabled={busy} onClick={() => setOpen(false)} className="ml-2 rounded border px-3 py-2">{t('tryIt.cancel')}</button>
      {error && <p role="alert">{t('tryIt.error')}</p>}
    </form>}
  </section>;
}
