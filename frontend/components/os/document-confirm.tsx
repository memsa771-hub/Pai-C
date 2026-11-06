'use client';

import { useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { formValues, startValue, type OsDocument, type UploadOptions, type VaultCheck } from '@/lib/os-documents';
import { fieldLabel } from '@/lib/os-programmes';

interface DocumentConfirmProps {
  document: OsDocument;
  onConfirm: (values: Record<string, unknown>) => void;
  onBack?: () => void;
  busy?: boolean;
  /** The page's one answer to GET /v1/uploads/options; off (the default) asks for nothing. */
  options?: UploadOptions;
}

/** "Check what we read" (Slice 3 spec §5): every field with the value read in an edit box, a mark where a check
 * failed, and one Confirm all. The student confirms every value (invariant 4). */
export function DocumentConfirm({ document, onConfirm, onBack, busy = false, options = { one_upload: false } }: DocumentConfirmProps) {
  const [text, setText] = useState<Record<string, string>>(
    () => Object.fromEntries(document.fields.map((f) => [f.field, startValue(f)])),
  );
  // P1-T7: with the one upload on, the Vault comparison: one note above the fields, a mark on the fields that differ.
  // A 404 (nothing to compare with) or any error shows nothing.
  const [check, setCheck] = useState<VaultCheck | null>(null);
  useEffect(() => {
    if (!options.one_upload) return;
    let active = true;
    workspaceApi.getOsVaultCheck(document.id).then((c) => { if (active) setCheck(c); }, () => {});
    return () => { active = false; };
  }, [options.one_upload, document.id]);
  const differs = new Set(check?.fields.filter((f) => f.outcome === 'differs').map((f) => f.field));
  return (
    <form className="flex w-full max-w-xl flex-col gap-3"
          onSubmit={(e) => { e.preventDefault(); onConfirm(formValues(document.fields, text)); }}>
      {check?.note && <p className="rounded-2xl bg-muted px-4 py-3 text-sm">{check.note}</p>}
      <p className="rounded-2xl bg-muted px-4 py-3 text-sm">We read this automatically; please check every value.</p>
      {document.fields.map((f) => {
        const id = `field-${document.id}-${f.field}`;
        const failed = f.check === 'check_failed';
        return (
          <div key={f.field} className="min-w-0">
            <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{f.label ?? fieldLabel(f.field)}</label>
            {differs.has(f.field) && check?.note && (
              <span id={`${id}-differs`} role="img" aria-label={check.note} title={check.note} data-testid={`differs-${f.field}`}
                    className="ml-1 text-xs font-medium text-amber-900">≠</span>
            )}
            <input id={id} value={text[f.field] ?? ''} aria-invalid={failed}
                   aria-describedby={[differs.has(f.field) && check?.note ? `${id}-differs` : '', failed ? `${id}-why` : ''].filter(Boolean).join(' ') || undefined}
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
