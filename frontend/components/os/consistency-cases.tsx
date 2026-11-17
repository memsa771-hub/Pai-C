'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { codeLabel, ruleLabel, type OsConsistencyCase } from '@/lib/os-consistency';

/** The consistency checks on the admin support page (P1-T10, R-05): open cases, each resolved with a note. */
export function ConsistencyCases({ cases, busy, onResolve }: {
  cases: OsConsistencyCase[]; busy: boolean; onResolve: (id: number, note: string) => void;
}) {
  return (
    <section aria-labelledby="consistency-heading" className="mt-8">
      <h2 id="consistency-heading" className="mb-3 text-base font-semibold">Consistency checks</h2>
      {cases.length === 0 ? (
        <p className="text-sm text-muted-foreground">No open consistency checks.</p>
      ) : (
        <ul className="flex flex-col gap-3 text-sm">
          {cases.map((c) => <CaseItem key={c.id} kase={c} busy={busy} onResolve={onResolve} />)}
        </ul>
      )}
    </section>
  );
}

function CaseItem({ kase, busy, onResolve }: { kase: OsConsistencyCase; busy: boolean;
                                             onResolve: (id: number, note: string) => void }) {
  const [note, setNote] = useState('');
  return (
    <li className="rounded-2xl border bg-card p-4 shadow-card">
      <p className="break-words font-medium">Rule {kase.rule}: {ruleLabel(kase.rule)}</p>
      <p className="mt-0.5 break-words text-xs">{kase.codes.map(codeLabel).join(', ')}</p>
      <p className="mt-0.5 break-words text-xs text-muted-foreground">
        Student {kase.student_ref} · plan {kase.plan_id ?? '—'} · first seen {new Date(kase.first_seen_at).toLocaleString()}
        {' '}· last seen {new Date(kase.last_seen_at).toLocaleString()}
      </p>
      <form className="mt-2 flex flex-col gap-2"
            onSubmit={(e) => { e.preventDefault(); if (note.trim()) onResolve(kase.id, note.trim()); }}>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="What you checked"
                  aria-label={`Note for check ${kase.id}`}
                  className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
        <Button size="sm" type="submit" disabled={busy || !note.trim()}>Resolve</Button>
      </form>
    </li>
  );
}
