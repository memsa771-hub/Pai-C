'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { CounselorGoalSummary } from '@/lib/roadmaps';

const FIELDS = [
  'stated_goal', 'goal_reason', 'subject_likes', 'field_interest',
  'envisioned_outcome', 'budget', 'timing', 'family_wish',
  'location_limits', 'study_mode',
] as const;

type Field = typeof FIELDS[number];

function words(entry: CounselorGoalSummary['summary'][string] | undefined): string {
  if (!entry) return '';
  if (entry.student_words) return entry.student_words;
  const value = entry.value;
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(String).join(', ');
  if (value && typeof value === 'object') {
    const parts = value as Record<string, unknown>;
    if (parts.title) return String(parts.title);
    if (parts.suggested_direction) return String(parts.suggested_direction);
    if (parts.amount != null) return [parts.amount, parts.currency, parts.period].filter(Boolean).join(' ');
  }
  return '';
}

export function CounselorGoalSummaryCard({ refreshKey, onSend }: {
  refreshKey: string | number;
  onSend: (message: string) => Promise<void>;
}) {
  const t = useT();
  const [draft, setDraft] = useState<CounselorGoalSummary | null>(null);
  const [values, setValues] = useState<Partial<Record<Field, string>>>({});
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    workspaceApi.getCounselorGoalSummary().then((result) => {
      if (!active) return;
      setDraft(result);
      setValues(Object.fromEntries(FIELDS.map((field) => [field, words(result.summary[field])])));
      setSent(false); setEditing(false);
    }).catch(() => { if (active) setDraft(null); });
    return () => { active = false; };
  }, [refreshKey]);

  if (!draft?.status) return null;
  const send = async (message: string) => {
    setBusy(true); setError('');
    try { await onSend(message); setSent(true); setEditing(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const saveEdits = () => {
    const changed = FIELDS.filter((field) => values[field]?.trim() !== words(draft.summary[field]).trim());
    if (!changed.length) { setEditing(false); return; }
    const correction = changed.map((field) => `${t(`counselorSummary.${field}`)}: ${values[field]?.trim() || 'I do not know yet'}`).join('; ');
    void send(`Please correct my goal summary. ${correction}`);
  };

  return <section className="rounded-xl border bg-card p-3 text-sm" aria-label={t('counselorSummary.title')}>
    <h3 className="font-semibold">{t('counselorSummary.title')}</h3>
    {editing ? <div className="mt-3 grid gap-2 sm:grid-cols-2">
      {FIELDS.map((field) => <label key={field} className="block text-xs font-medium">
        {t(`counselorSummary.${field}`)}
        <input value={values[field] || ''} onChange={(event) => setValues((current) => ({ ...current, [field]: event.target.value }))}
          className="mt-1 w-full rounded-lg border bg-background px-2 py-1.5 text-sm" />
      </label>)}
    </div> : <dl className="mt-2 grid gap-2 sm:grid-cols-2">{FIELDS.filter((field) => draft.summary[field]).map((field) =>
      <div key={field}><dt className="text-xs text-muted-foreground">{t(`counselorSummary.${field}`)}</dt>
        <dd>{words(draft.summary[field]) || t('counselorSummary.notProvided')}</dd></div>)}</dl>}
    {draft.status === 'confirmed' && <p className="mt-3 text-xs text-muted-foreground">{t('counselorSummary.confirmed')}</p>}
    {editing && <p className="mt-2 text-xs text-muted-foreground">{t('counselorSummary.editHint')}</p>}
    {sent && <p role="status" className="mt-2 text-xs">{t('counselorSummary.sent')}</p>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
    {draft.status === 'awaiting_confirmation' && <div className="mt-3 flex flex-wrap gap-2">
      {editing ? <>
        <button type="button" disabled={busy} onClick={saveEdits} className="rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground disabled:opacity-50">{t('counselorSummary.saveEdits')}</button>
        <button type="button" disabled={busy} onClick={() => setEditing(false)} className="rounded-lg border px-3 py-1.5 text-xs">{t('common.cancel')}</button>
      </> : <>
        <button type="button" disabled={busy} onClick={() => void send('Yes, that summary is correct. Please research my options.')}
          className="rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground disabled:opacity-50">{t('counselorSummary.confirm')}</button>
        <button type="button" disabled={busy} onClick={() => setEditing(true)} className="rounded-lg border px-3 py-1.5 text-xs">{t('counselorSummary.edit')}</button>
      </>}
    </div>}
  </section>;
}
