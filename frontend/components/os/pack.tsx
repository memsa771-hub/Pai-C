'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  DATA_SHEET_KEY,
  canApprove,
  feeValue,
  fileFor,
  packStatusLabel,
  programmeTitle,
  type OsPack,
  type OsPackFile,
} from '@/lib/os-packs';

/** "Your application packs" (Slice 6a spec §5): one row per programme in the plan, with its status. */
export function PackList({ packs, onOpen }: { packs: OsPack[]; onOpen: (p: OsPack) => void }) {
  if (packs.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted-foreground">No programmes in your plan yet.</p>;
  }
  return (
    <ul className="mx-auto flex w-full max-w-md flex-col gap-2">
      {packs.map((p) => (
        <li key={p.programme_ref} className="rounded-lg border bg-card p-3 text-sm">
          <button type="button" onClick={() => onOpen(p)} className="w-full break-words text-left">
            <span className="font-medium">{programmeTitle(p)}</span>
            <span className="text-muted-foreground"> · {packStatusLabel(p)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

interface PackViewProps {
  pack: OsPack;
  busy: boolean;
  onTick: (key: string, ticked: boolean) => void;
  onAdd: (label: string) => void;
  onApprove: () => void;
  onDownload: (file: OsPackFile) => void;
  onRebuild: () => void;
  onDetails: () => void;
}

/** One programme's pack: how to apply, fees, the checklist with downloads, the data sheet, and Approve. */
export function PackView({ pack, busy, onTick, onAdd, onApprove, onDownload, onRebuild, onDetails }: PackViewProps) {
  const [extra, setExtra] = useState('');
  const sheet = fileFor(pack, DATA_SHEET_KEY);
  const sections = [...new Set(pack.data_sheet.map((r) => r.section))];
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4 text-sm">
      <p className="rounded-md bg-muted p-2">You submit and pay yourself. We never send anything for you.</p>
      {pack.status === 'building' && <p className="text-muted-foreground">Your pack is being prepared…</p>}
      {pack.status === 'failed' && (
        <p className="text-destructive">
          We could not prepare this pack.{' '}
          <Button size="sm" variant="outline" disabled={busy} onClick={onRebuild}>Try again</Button>
        </p>
      )}

      <section aria-label="How to apply" className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 font-semibold">How to apply</h2>
        <ol className="flex list-none flex-col gap-2">
          {pack.instructions.map((s) => (
            <li key={s.n} className="break-words">
              {s.n}. {s.text}{' '}
              {s.source_url && (
                <a href={s.source_url} target="_blank" rel="noopener noreferrer"
                   className="text-primary underline-offset-2 hover:underline">source</a>
              )}
            </li>
          ))}
        </ol>
        {pack.fees.length > 0 && (
          <dl className="mt-3 flex flex-col gap-1">
            {pack.fees.map((f) => (
              <div key={f.label} className="flex flex-wrap gap-x-2">
                <dt className="text-muted-foreground">{f.label}:</dt>
                <dd className="break-words">
                  {feeValue(f)}{' '}
                  {f.source_url && (
                    <a href={f.source_url} target="_blank" rel="noopener noreferrer"
                       className="text-primary underline-offset-2 hover:underline">source</a>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section aria-label="Checklist" className="rounded-lg border bg-card p-3">
        <h2 className="mb-2 font-semibold">Checklist</h2>
        <ul className="flex flex-col gap-3">
          {pack.checklist.map((i) => {
            const file = fileFor(pack, i.key);
            const mark = i.state === 'ready' || (i.state === 'manual' && i.ticked) ? '✓' : i.state === 'manual' ? '☐' : '⚠';
            return (
              <li key={i.key} className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  {i.tickable ? (
                    <label className="flex min-w-0 flex-1 items-center gap-2 break-words">
                      <input type="checkbox" checked={i.ticked} disabled={busy}
                             onChange={(e) => onTick(i.key, e.target.checked)} />
                      {i.label}
                    </label>
                  ) : (
                    <span className="min-w-0 flex-1 break-words">{mark} {i.label}</span>
                  )}
                  {file && (
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => onDownload(file)}>Download</Button>
                  )}
                </div>
                {i.reasons.map((r) => <p key={r} className="mt-0.5 break-words text-xs text-amber-900">⚠ {r}</p>)}
              </li>
            );
          })}
        </ul>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (extra.trim()) { onAdd(extra.trim()); setExtra(''); } }}>
          <input value={extra} onChange={(e) => setExtra(e.target.value)} placeholder="Something else the portal asks for"
                 className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1" />
          <Button size="sm" type="submit" variant="outline" disabled={busy}>Add</Button>
        </form>
      </section>

      <section aria-label="Data sheet" className="rounded-lg border bg-card p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Data sheet</h2>
          {sheet && <Button size="sm" variant="outline" disabled={busy} onClick={() => onDownload(sheet)}>Download</Button>}
        </div>
        {sections.map((section) => (
          <div key={section} className="mb-3">
            <h3 className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{section}</h3>
            <dl className="flex flex-col gap-1">
              {pack.data_sheet.filter((r) => r.section === section).map((r) => (
                <div key={r.key} className="flex flex-wrap items-center gap-x-2">
                  <dt className="text-muted-foreground">{r.label}</dt>
                  <dd className="flex min-w-0 flex-1 items-center justify-end gap-2 break-words">
                    {r.value !== null ? (
                      <>
                        <span className="break-words">{r.value}</span>
                        <Button size="sm" variant="ghost" type="button"
                                onClick={() => void navigator.clipboard?.writeText(r.value ?? '')}>Copy</Button>
                      </>
                    ) : (
                      <span className={r.gap ? 'text-amber-900' : 'text-muted-foreground'}>— missing</span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
        <Button size="sm" variant="outline" onClick={onDetails}>A few more details</Button>
      </section>

      {pack.approved ? (
        <p className="font-medium">Approved ✓</p>
      ) : (
        <Button disabled={busy || !canApprove(pack)} onClick={onApprove}>Approve pack</Button>
      )}
    </div>
  );
}
