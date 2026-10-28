'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { formValues, startValue, type OsDocument } from '@/lib/os-documents';
import { fieldLabel } from '@/lib/os-programmes';

interface DocumentConfirmProps {
  document: OsDocument;
  onConfirm: (values: Record<string, unknown>) => void;
  onBack?: () => void;
  busy?: boolean;
}

/** "Check what we read" (Slice 3 spec §5): every field with the value read in an edit box, a mark where a check
 * failed, and one Confirm all. The student confirms every value (invariant 4). */
export function DocumentConfirm({ document, onConfirm, onBack, busy = false }: DocumentConfirmProps) {
  const [text, setText] = useState<Record<string, string>>(
    () => Object.fromEntries(document.fields.map((f) => [f.field, startValue(f)])),
  );
  return (
    <form className="mx-auto flex w-full max-w-md flex-col gap-3"
          onSubmit={(e) => { e.preventDefault(); onConfirm(formValues(document.fields, text)); }}>
      <p className="rounded-md bg-muted p-2 text-sm">We read this automatically; please check every value.</p>
      {document.fields.map((f) => {
        const id = `field-${document.id}-${f.field}`;
        const failed = f.check === 'check_failed';
        return (
          <div key={f.field} className="min-w-0">
            <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{f.label ?? fieldLabel(f.field)}</label>
            <input id={id} value={text[f.field] ?? ''} aria-invalid={failed}
                   aria-describedby={failed ? `${id}-why` : undefined}
                   onChange={(e) => setText((t) => ({ ...t, [f.field]: e.target.value }))}
                   className={`mt-0.5 w-full min-w-0 rounded-md border bg-background px-2 py-1.5 text-sm ${failed ? 'border-amber-500' : ''}`} />
            {failed && (
              <ul id={`${id}-why`} className="mt-1 list-none text-xs text-amber-900">
                {f.reasons.map((r) => <li key={r} className="break-words">⚠ {r}</li>)}
              </ul>
            )}
            {f.check === 'missing' && (
              <p className="mt-1 text-xs text-muted-foreground">not found on the document; leave empty if it has none</p>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap gap-2 pt-1">
        <Button type="submit" disabled={busy}>Confirm all</Button>
        {onBack && <Button type="button" variant="outline" onClick={onBack} disabled={busy}>Back</Button>}
      </div>
    </form>
  );
}
