'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { admittedRefs, fundsLine, programmeLabel, type OsFunds, type OsVisa } from '@/lib/os-visa';

/** Which programme the visa file is for (Slice 6b spec S6b-D8): one from the plan, pre-selected if only one admitted
 * the student. With two admissions both are marked and the student chooses first: nothing is built before (Slice 9
 * Task 11). */
export function VisaChoice({ visa, busy, onChoose }: { visa: OsVisa; busy: boolean; onChoose: (ref: string) => void }) {
  const admitted = admittedRefs(visa);
  return (
    <section aria-label="Programme" className="rounded-lg border bg-card p-3 text-sm">
      {visa.programme_ref === null && admitted.length > 1 && (
        <p className="mb-2 break-words font-medium">
          You were admitted to more than one programme. Choose the one your visa is for: we prepare the visa file
          once you choose.
        </p>
      )}
      <label className="flex flex-col gap-1 break-words">
        <span className="font-semibold">
          {visa.programme_ref ? 'For' : 'Choose the programme your visa is for'}
        </span>
        <select value={visa.programme_ref ?? ''} disabled={busy} onChange={(e) => e.target.value && onChoose(e.target.value)}
                className="w-full min-w-0 rounded-md border bg-background px-2 py-1">
          {visa.programme_ref === null && <option value="">Choose…</option>}
          {visa.programmes.map((p) => (
            <option key={p.programme_ref} value={p.programme_ref}>
              {programmeLabel(p)}{admitted.includes(p.programme_ref) ? ' (admitted)' : ''}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-2 break-words text-muted-foreground">
        This checklist is a default: check it against the embassy portal&apos;s own list.
      </p>
    </section>
  );
}

/** What the student must show for the visa (S6b-D4): the amount, its status and source, and other proof. */
export function VisaFunds({ funds, busy, onReduction }: { funds: OsFunds | null; busy: boolean;
                                                         onReduction: (amount: number) => void }) {
  const [amount, setAmount] = useState(String(funds?.reduction ?? 0));
  return (
    <section aria-label="Funds" className="rounded-lg border bg-card p-3 text-sm">
      <h2 className="mb-1 font-semibold">Funds you need: {fundsLine(funds)}</h2>
      {funds && funds.required !== null && (
        <p className="break-words text-muted-foreground">
          {funds.status !== 'confirmed' && <span className="text-amber-900">⚠ {funds.status} </span>}
          {funds.reduction > 0 && <>after {funds.reduction} {funds.currency_label} of other proof </>}
          {funds.url && (
            <a href={funds.url} target="_blank" rel="noopener noreferrer"
               className="text-primary underline-offset-2 hover:underline">source</a>
          )}
        </p>
      )}
      <form className="mt-2 flex flex-wrap items-center gap-2"
            onSubmit={(e) => { e.preventDefault(); const n = Number(amount); if (Number.isFinite(n) && n >= 0) onReduction(n); }}>
        <label className="flex min-w-0 flex-1 items-center gap-2 break-words">
          Scholarship or other proof
          <input type="number" min={0} step="any" value={amount} onChange={(e) => setAmount(e.target.value)}
                 className="w-24 min-w-0 rounded-md border bg-background px-2 py-1" />
        </label>
        <Button size="sm" type="submit" variant="outline" disabled={busy}>Save</Button>
      </form>
    </section>
  );
}
