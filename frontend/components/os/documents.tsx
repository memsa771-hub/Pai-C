'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  ACCEPT,
  canConfirm,
  checkFailedCount,
  docStatusLabel,
  findingText,
  typeLabel,
  type OsDocType,
  type OsDocument,
  type OsFinding,
} from '@/lib/os-documents';

interface DocumentListProps {
  documents: OsDocument[];
  findings: OsFinding[];
  docTypes: OsDocType[];
  onUpload: (file: File, docType: string) => void;
  onOpen: (doc: OsDocument) => void;
  onResolve: (finding: OsFinding, value: string) => void;
  /** A document that cannot be opened (failed, waiting, reading): the student can still remove it. */
  onDelete: (doc: OsDocument) => void;
  busy?: boolean;
}

/** "Your documents" (Slice 3 spec §5): mobile-first (360 px). Upload with a type, each document's status, and
 * the findings across documents, each with a choice of the values found. */
export function DocumentList({ documents, findings, docTypes, onUpload, onOpen, onResolve, onDelete, busy = false }: DocumentListProps) {
  const [docType, setDocType] = useState(docTypes[0]?.key ?? '');
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border bg-card p-3">
        <label className="inline-flex cursor-pointer items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
          + Upload
          <input type="file" accept={ACCEPT} className="sr-only" disabled={busy || !docType}
                 onChange={(e) => {
                   const file = e.target.files?.[0];
                   if (file) onUpload(file, docType);
                   e.target.value = '';
                 }} />
        </label>
        <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
          <span className="text-muted-foreground">type:</span>
          <select value={docType} onChange={(e) => setDocType(e.target.value)}
                  className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm">
            {docTypes.map((t) => (
              <option key={t.key} value={t.key}>{t.label}</option>
            ))}
          </select>
        </label>
      </div>

      {documents.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-muted-foreground">
          No documents yet. Upload your passport, degrees, transcripts and test results.
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {documents.map((d) => (
            <DocumentRow key={d.id} doc={d} docTypes={docTypes} onOpen={onOpen} onDelete={onDelete} busy={busy} />
          ))}
        </ul>
      )}

      {findings.map((f) => (
        <section key={f.id} role="alert" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
          <p className="break-words">⚠ {findingText(f, documents, docTypes)}</p>
          <details className="mt-2">
            <summary className="cursor-pointer font-medium">Choose</summary>
            <div className="mt-2 flex flex-wrap gap-2">
              {f.items.map((i) => (
                <Button key={`${i.document_id}:${i.value}`} size="sm" variant="outline" disabled={busy}
                        className="h-auto max-w-full break-words whitespace-normal text-left"
                        onClick={() => onResolve(f, i.value)}>{i.value}</Button>
              ))}
            </div>
          </details>
        </section>
      ))}
    </div>
  );
}

interface DocumentRowProps {
  doc: OsDocument;
  docTypes: OsDocType[];
  onOpen: (d: OsDocument) => void;
  onDelete: (d: OsDocument) => void;
  busy: boolean;
}

function DocumentRow({ doc, docTypes, onOpen, onDelete, busy }: DocumentRowProps) {
  const failed = checkFailedCount(doc);
  const open = canConfirm(doc);
  const summary = (
    <>
      <span className="font-medium">{typeLabel(doc.doc_type, docTypes)}</span>
      <span className="text-muted-foreground"> · {docStatusLabel(doc)}</span>
      {failed > 0 && doc.status !== 'confirmed' && (
        <span className="ml-1 text-amber-900"> · ⚠ check {failed} field{failed === 1 ? '' : 's'}</span>
      )}
    </>
  );
  return (
    <li className="rounded-lg border bg-card p-3 text-sm">
      {open ? (
        <button type="button" onClick={() => onOpen(doc)} className="w-full break-words text-left">{summary}</button>
      ) : (
        <p className="break-words">{summary}</p>
      )}
      <p className="mt-0.5 break-words text-xs text-muted-foreground">{doc.filename}</p>
      {doc.status === 'needs_student' && doc.detected_type && (
        <p className="mt-1 break-words text-xs text-amber-900">This looks like a {doc.detected_type}. Is that right?</p>
      )}
      {doc.status === 'failed' && (
        <p className="mt-1 break-words text-xs text-destructive">
          {doc.error ? `${doc.error} ` : ''}You can delete it and upload the file again.
        </p>
      )}
      {!open && (
        <Button size="sm" variant="ghost" className="mt-1 h-auto px-0 text-xs text-destructive" disabled={busy}
                onClick={() => onDelete(doc)}>Delete</Button>
      )}
    </li>
  );
}
