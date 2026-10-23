'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { OsSupportCase } from '@/lib/os-replan';

/** The admin support inbox (Slice 7 spec §5): open cases, each resolved with a note, optionally resuming changes. */
export function SupportList({ cases, busy, onResolve }: {
  cases: OsSupportCase[]; busy: boolean; onResolve: (id: number, note: string, unpause: boolean) => void;
}) {
  if (cases.length === 0) {
    return <p className="text-sm text-muted-foreground">No open cases.</p>;
  }
  return (
    <ul className="flex flex-col gap-3 text-sm">
      {cases.map((c) => <CaseItem key={c.id} kase={c} busy={busy} onResolve={onResolve} />)}
    </ul>
  );
}

function CaseItem({ kase, busy, onResolve }: { kase: OsSupportCase; busy: boolean;
                                             onResolve: (id: number, note: string, unpause: boolean) => void }) {
  const [note, setNote] = useState('');
  const [unpause, setUnpause] = useState(kase.changes_paused);
  return (
    <li className="rounded-lg border bg-card p-3">
      <p className="break-words font-medium">{kase.reason}</p>
      <p className="mt-0.5 break-words text-xs text-muted-foreground">
        Plan {kase.plan_id} · student {kase.student_ref} · {new Date(kase.created_at).toLocaleString()}
        {kase.changes_paused && ' · changes paused'}
      </p>
      {kase.status === 'open' && (
        <form className="mt-2 flex flex-col gap-2"
              onSubmit={(e) => { e.preventDefault(); if (note.trim()) onResolve(kase.id, note.trim(), unpause); }}>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="What you did"
                    className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={unpause} onChange={(e) => setUnpause(e.target.checked)} />
            Resume automatic changes for this plan
          </label>
          <Button size="sm" type="submit" disabled={busy || !note.trim()}>Resolve</Button>
        </form>
      )}
      {kase.resolution && <p className="mt-2 break-words text-muted-foreground">Resolved: {kase.resolution}</p>}
    </li>
  );
}
