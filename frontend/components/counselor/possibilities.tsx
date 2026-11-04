'use client';
import { useEffect, useState } from 'react';
import { ArrowRight, Bookmark, Compass, X } from 'lucide-react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import { DEFAULT_LOCALE } from '@/lib/i18n/locales';
import type { Possibility } from '@/lib/possibilities';
import { Button } from '@/components/ui/button';
import { FieldNotes, FitList, PathCardView } from './path-card';
import { openWorkspaceView } from './workspace-link';
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
  return <PathCardView compact headingLevel={3} id={value.id} tone={tone} title={value.title} whyLabel={copy.why} why={value.why} evidence={value.evidence}
    quote={value.evidence[0]?.text} fit={value.fit} studyField={value.study_field} status={t(`possibilities.${value.status}`)} statusTone={statusTone[value.status]} error={error}
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

/** The analyzer's result in chat: which paths it found and how each fits, at
 * a glance, with the way to the full picture. */
export type PathSnapshot = Pick<Possibility, 'id' | 'title' | 'why' | 'fit' | 'study_field'>;

/** `snapshot`: the paths as they stood when PAI posted the message. A message keeps what it said; a later run's
 * list is one tap away, with a note when it differs. Older messages without one read the current list. */
export function PathsFound({ ids, snapshot, newest }: { ids: string[]; snapshot?: PathSnapshot[]; newest?: boolean }) {
  const [rows, setRows] = useState<Possibility[] | null>(null);
  useEffect(() => {
    let active = true;
    setRows(null); // what is loaded always belongs to the current ids and mode
    (newest ? workspaceApi.getCurrentPaths() : workspaceApi.getPossibilities()).then(value => { if (active) setRows(value); }).catch(() => {});
    return () => { active = false; };
  }, [ids.join(), newest]); // eslint-disable-line react-hooks/exhaustive-deps
  const current = (rows ?? []).filter(row => row.status !== 'dismissed');
  // The newest card shows the current list once it has loaded; until then (or if the call fails) its snapshot.
  const found: PathSnapshot[] = newest && rows !== null ? current
    : snapshot?.length ? snapshot : current.filter(row => ids.includes(row.id));
  const changed = !newest && !!snapshot?.length && rows !== null
    && (current.filter(row => row.source === 'analyzer').map(row => row.id).sort().join() !== [...ids].sort().join());
  if (!found.length) return null;
  return (
    <section className="my-3 max-w-lg rounded-3xl border bg-card p-5 shadow-card">
      <h3 className="flex items-center gap-2 text-base font-bold"><Compass aria-hidden className="size-5 text-brand" />{copy.pathsFoundTitle}</h3>
      <p className="mt-1 text-sm text-muted-foreground">{copy.pathsFoundBody[new Intl.PluralRules(DEFAULT_LOCALE).select(found.length) === 'one' ? 'one' : 'other'].replace('{count}', String(found.length))}</p>
      <ul className="mt-4 space-y-4">
        {found.map(row => (
          <li key={row.id} className="border-t pt-4 first:border-t-0 first:pt-0">
            <p className="font-semibold">{row.title}</p>
            <FieldNotes field={row.study_field} className="mt-1.5" />
            {!!row.fit?.length && <div className="mt-2"><FitList items={row.fit} limit={3} /></div>}
          </li>
        ))}
      </ul>
      {changed && <p className="mt-4 text-sm text-muted-foreground">{copy.pathsFoundChanged}</p>}
      <Button size="tap" className="mt-5" onClick={() => openWorkspaceView('paths')}>{copy.pathsFoundOpen}<ArrowRight aria-hidden /></Button>
    </section>
  );
}
