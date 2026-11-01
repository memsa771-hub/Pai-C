'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { OsSheetRow } from '@/lib/os-packs';

interface PackDetailsProps {
  rows: OsSheetRow[];
  busy: boolean;
  onSave: (fields: Record<string, string>) => void;
  onBack: () => void;
  /** Values PAI already has (email, city, country), keyed like the rows: they fill empty fields for the student to
   * check, so nothing PAI knows is asked again from nothing. */
  suggested?: Record<string, string>;
}

/** "A few more details" (Slice 6a spec S6a-D4): the data-sheet fields no document shows; the student types them. */
export function PackDetails({ rows, busy, onSave, onBack, suggested = {} }: PackDetailsProps) {
  const entered = rows.filter((r) => r.entered);
  const [text, setText] = useState<Record<string, string>>(
    () => Object.fromEntries(entered.map((r) => [r.key, r.value ?? suggested[r.key] ?? ''])),
  );
  const fromProfile = entered.some((r) => r.value === null && suggested[r.key]);
  return (
    <form className="flex w-full max-w-xl flex-col gap-3 text-sm"
          onSubmit={(e) => { e.preventDefault(); onSave(text); }}>
      <p className="rounded-2xl bg-muted px-4 py-3">These are not on your documents. Type them as the portal should show them.</p>
      {fromProfile && (
        <p className="rounded-2xl bg-brand-soft px-4 py-3">We filled in what PAI already knows from your profile. Check each one before you save.</p>
      )}
      {entered.map((r) => (
        <div key={r.key} className="min-w-0">
          <label htmlFor={`detail-${r.key}`} className="text-xs font-medium text-muted-foreground">
            {r.label}{r.gap ? ' (needed)' : ''}
          </label>
          <input id={`detail-${r.key}`} value={text[r.key] ?? ''}
                 onChange={(e) => setText((t) => ({ ...t, [r.key]: e.target.value }))}
                 className="mt-0.5 w-full min-w-0 rounded-md border bg-background px-2 py-1.5" />
          {r.hint && <p className="mt-0.5 text-xs text-muted-foreground">{r.hint}</p>}
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>Save</Button>
        <Button type="button" variant="outline" disabled={busy} onClick={onBack}>Back</Button>
      </div>
    </form>
  );
}
