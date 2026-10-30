'use client';

import { Button } from '@/components/ui/button';
import { answerBy, opText, type OsProposal } from '@/lib/os-replan';

/** A suggested change to the student's plan (Slice 7 spec §5): what, why, by when, Accept or Decline. */
export function ProposalCard({ proposal, names, busy, onAccept, onDecline }: {
  proposal: OsProposal; names: Record<string, string>; busy: boolean; onAccept: () => void; onDecline: () => void;
}) {
  const by = answerBy(proposal);
  return (
    <li className="rounded-lg border bg-card p-3 text-sm">
      <p className="font-medium">We suggest:</p>
      <ul className="mt-1 flex list-disc flex-col gap-0.5 pl-5">
        {proposal.ops.map((op, i) => <li key={i} className="break-words">{opText(op, names)}</li>)}
      </ul>
      <p className="mt-2 font-medium">Why:</p>
      <ul className="mt-1 flex flex-col gap-0.5 text-muted-foreground">
        {[...new Set(proposal.reasons)].map((r) => <li key={r} className="break-words">{r}</li>)}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" disabled={busy} onClick={onAccept}>Accept</Button>
        <Button size="sm" variant="outline" disabled={busy} onClick={onDecline}>Decline</Button>
        {by && <span className="text-xs text-muted-foreground">Answer by {by}</span>}
      </div>
    </li>
  );
}

/** Shown while a person checks the plan (S7-D9): automatic changes are paused. */
export function PausedBanner() {
  return (
    <p role="status" className="mb-3 break-words rounded-md bg-amber-50 p-2 text-sm text-amber-900">
      Changes are paused while a person checks your plan.
    </p>
  );
}
