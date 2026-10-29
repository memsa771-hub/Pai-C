'use client';

import { newestFirst, opText, type OsChange } from '@/lib/os-replan';

/** "What changed" (Slice 7 spec §5): the plan's changes, newest first, each with why and when. */
export function ChangesList({ changes, names }: { changes: OsChange[]; names: Record<string, string> }) {
  if (changes.length === 0) {
    return <p className="text-sm text-muted-foreground">No suggested changes yet.</p>;
  }
  return (
    <ul className="flex flex-col gap-2 text-sm">
      {newestFirst(changes).map((c) => (
        <li key={c.proposal_id} className="rounded-lg border bg-card p-3">
          <p className="text-xs text-muted-foreground">
            {new Date(c.at).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {c.ops.map((op, i) => <li key={i} className="break-words">{opText(op, names)}</li>)}
          </ul>
          <p className="mt-1 break-words text-muted-foreground">{[...new Set(c.reasons)].join(' ')}</p>
        </li>
      ))}
    </ul>
  );
}
