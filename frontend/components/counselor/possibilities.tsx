'use client';
import { useEffect, useState } from 'react';
import { Bookmark, Compass, X } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { Possibility } from '@/lib/possibilities';
import { Button } from '@/components/ui/button';
import { PathCardView } from './path-card';
import { tonesByOrder, type Tone } from '@/components/pai';
import copy from './workspace/copy.json';

const statusTone = { suggested: 'blue', exploring: 'blue', saved: 'success', dismissed: 'neutral', chosen: 'success' } as const;

export function PossibilityCard({ value, onChange, tone }: { value: Possibility; onChange: (value: Possibility) => void; tone?: Tone }) {
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
  return <PathCardView compact headingLevel={3} id={value.id} tone={tone} title={value.title} whyLabel={copy.why} why={value.why}
    quote={value.evidence[0]?.text} status={t(`possibilities.${value.status}`)} statusTone={statusTone[value.status]} error={error}
    actions={<>
      {(['suggested', 'saved', 'dismissed'].includes(value.status)) && <Button size="tap" disabled={busy} onClick={() => void action('explore')}><Compass aria-hidden />{t('possibilities.explore')}</Button>}
      {(['suggested', 'dismissed'].includes(value.status)) && <Button size="tap" variant="soft" disabled={busy} onClick={() => void action('save')}><Bookmark aria-hidden />{t('possibilities.save')}</Button>}
      {(['suggested', 'saved', 'exploring'].includes(value.status)) && <Button size="tap" variant="ghost" disabled={busy} onClick={() => void action('dismiss')}><X aria-hidden />{t('possibilities.dismiss')}</Button>}
    </>} />;
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
  const tones = tonesByOrder(rows.map(row => row.id));
  if (failed) return <p role="alert" className="text-sm font-medium text-danger-ink">{t('possibilities.error')}</p>;
  if (!selected.length) return null;
  return <section>{!id && <h2 className="mt-5 text-lg font-bold">{t('possibilities.title')}</h2>}
    {selected.map(row => <PossibilityCard key={row.id} value={row} tone={tones[row.id]}
      onChange={updated => { setRows(current => current.map(item => item.id === updated.id ? updated : item)); onUpdated?.(); }} />)}
  </section>;
}
