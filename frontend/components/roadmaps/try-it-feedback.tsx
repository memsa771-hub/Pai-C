'use client';
import { useState } from 'react';
import { Check, Clock, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { Roadmap } from '@/lib/roadmaps';
import { PAI_PRIMARY_CONVERSATION_ID } from '@/lib/primary-conversation';

export function TryItFeedback({ roadmap, headingLevel = 4 }: { roadmap: Roadmap; headingLevel?: 2 | 3 | 4 }) {
  const Heading = `h${headingLevel}` as const;
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
  const chip = (on: boolean) => `min-h-11 rounded-2xl border-2 px-4 text-sm font-semibold transition-colors ${on ? 'border-foreground bg-secondary text-foreground ring-1 ring-foreground' : 'border-border bg-card hover:border-foreground/30'}`;
  return <section className="min-w-0 space-y-3 rounded-3xl border border-primary/15 bg-brand-soft/60 p-5">
    <Heading className="flex items-center gap-2 font-bold"><Sparkles aria-hidden className="size-5 text-tone-violet-ink" />{t('tryIt.title')}</Heading>
    <p className="text-xs font-semibold text-primary">{t(`tryIt.${trial.kind}`)}</p>
    <p className="text-sm leading-relaxed">{trial.what}</p>
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Clock aria-hidden className="size-3.5" />{trial.time_needed}</p>
    {!!trial.questions.length && <ol className="list-inside list-decimal space-y-1 text-sm">{trial.questions.map((question, index) => <li key={index}>{question}</li>)}</ol>}
    {sent ? <p role="status" className="flex items-center gap-2 text-sm font-medium text-success-ink"><Check aria-hidden className="size-4" />{t('tryIt.sent')}</p>
      : !open && <Button type="button" size="tap" onClick={() => setOpen(true)}>{t('tryIt.tried')}</Button>}
    {open && <form onSubmit={submit} className="space-y-3 rounded-2xl bg-card p-4">
      <fieldset disabled={busy}><legend className="text-sm font-semibold">{t('tryIt.feeling')}</legend>
        <div className="mt-2 flex flex-wrap gap-2">{(['more', 'okay', 'notForMe'] as const).map(value =>
          <button type="button" key={value} aria-pressed={feeling === value} onClick={() => setFeeling(value)}
            className={chip(feeling === value)}>{t(`tryIt.${value}`)}</button>)}</div>
      </fieldset>
      <label className="block text-sm font-medium">{t('tryIt.note')}<textarea value={note} disabled={busy} onChange={event => setNote(event.target.value)}
        className="mt-1 min-h-20 w-full rounded-xl border bg-background p-3 text-base sm:text-sm" /></label>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="tap" disabled={busy || !feeling}>{t('tryIt.send')}</Button>
        <Button type="button" size="tap" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>{t('tryIt.cancel')}</Button>
      </div>
      {error && <p role="alert" className="text-sm font-medium text-danger-ink">{t('tryIt.error')}</p>}
    </form>}
  </section>;
}
