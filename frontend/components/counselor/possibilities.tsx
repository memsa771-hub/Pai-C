'use client';
import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { Possibility } from '@/lib/possibilities';

export function PossibilityCard({ value, onChange }: { value: Possibility; onChange: (value: Possibility) => void }) {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const action = async (kind: 'explore' | 'save' | 'dismiss') => {
    if (busy) return;
    setBusy(true); setError('');
    try { onChange(await workspaceApi.changePossibility(value.id, kind)); }
    catch { setError(t('possibilities.error')); }
    finally { setBusy(false); }
  };
  return <article className="my-3 min-w-0 rounded-lg border p-3 text-sm break-words">
    <h3 className="font-medium">{value.title}</h3><p>{value.why}</p>
    <p className="text-muted-foreground">{t(`possibilities.${value.status}`)}</p>
    <div className="mt-2 flex flex-wrap gap-2">
      {(['suggested', 'saved', 'dismissed'].includes(value.status)) && <button disabled={busy} className="rounded border px-3 py-2" onClick={() => void action('explore')}>{t('possibilities.explore')}</button>}
      {(['suggested', 'dismissed'].includes(value.status)) && <button disabled={busy} className="rounded border px-3 py-2" onClick={() => void action('save')}>{t('possibilities.save')}</button>}
      {(['suggested', 'saved', 'exploring'].includes(value.status)) && <button disabled={busy} className="rounded border px-3 py-2" onClick={() => void action('dismiss')}>{t('possibilities.dismiss')}</button>}
    </div>{error && <p role="alert">{error}</p>}
  </article>;
}

export function Possibilities({ id, refreshKey, onUpdated }: { id?: string; refreshKey?: unknown; onUpdated?: () => void }) {
  const t = useT();
  const [rows, setRows] = useState<Possibility[]>([]);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let active = true;
    workspaceApi.getPossibilities().then(value => { if (active) { setRows(value); setFailed(false); } })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [id, refreshKey]);
  const selected = rows.filter(row => id ? row.id === id : row.status !== 'chosen');
  if (failed) return <p role="alert">{t('possibilities.error')}</p>;
  if (!selected.length) return null;
  return <section>{!id && <h2 className="mt-5 text-lg font-semibold">{t('possibilities.title')}</h2>}
    {selected.map(row => <PossibilityCard key={row.id} value={row}
      onChange={updated => { setRows(current => current.map(item => item.id === updated.id ? updated : item)); onUpdated?.(); }} />)}
  </section>;
}
