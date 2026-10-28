'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { OsHeader } from '@/components/os/os-header';
import { ConsentCard } from '@/components/os/consent-card';
import { DocumentConfirm } from '@/components/os/document-confirm';
import { DocumentList } from '@/components/os/documents';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsConsent } from '@/lib/os-consent';
import { typeLabel, type OsDocuments, type OsDocument } from '@/lib/os-documents';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

const POLL_MS = 4000; // while a document waits or is being read

/** The API's reason for a refused call ("API 409: this file is already uploaded" -> the reason). */
function reason(e: unknown, fallback: string): string {
  const m = e instanceof Error ? /^API \d+: ([\s\S]+)$/.exec(e.message) : null;
  if (!m) return fallback;
  try {
    const detail = (JSON.parse(m[1]) as { detail?: unknown }).detail;
    return typeof detail === 'string' ? detail : fallback;
  } catch {
    return m[1].length < 200 ? m[1] : fallback;
  }
}

/** PAI OS documents: /<workspace>/os-documents. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsDocumentsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [data, setData] = useState<OsDocuments | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [consent, setConsent] = useState<OsConsent | null>(null);
  const [refused, setRefused] = useState(false);

  // Slice 9a: uploading needs consent to the current pilot terms; the card shows until the student agrees.
  const loadConsent = useCallback(() => workspaceApi.getOsConsent().then(
    (c) => { setConsent(c); if (c.agreed) setRefused(false); return c; },
    () => null,
  ), []);

  const load = useCallback(() => workspaceApi.getOsDocuments().then(
    (d) => { setData(d); setError(null); },
    () => setError('Could not load your documents. Please try again.'),
  ), []);

  useEffect(() => {
    if (!OS_UI_ENABLED || loading) return;
    if (!user) {
      goToSignIn();
      return;
    }
    // Placement AI: the bearer alone authorizes the call (no workspace token in the browser).
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    load();
    void loadConsent();
  }, [loading, user, idToken, workspaceId, load, loadConsent]);

  const waiting = data?.documents.some((d) => d.status === 'uploaded' || d.status === 'reading') ?? false;
  useEffect(() => {
    if (!waiting) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [waiting, load]);

  if (!OS_UI_ENABLED) notFound();

  async function act(fn: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(reason(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File, docType: string) {
    setBusy(true);
    try {
      await workspaceApi.uploadOsDocument(file, docType);
      await load();
    } catch (e) {
      const now = await loadConsent();
      if (now && !now.agreed) {  // refused for missing consent (the terms may have changed): the card asks
        setRefused(true);
        setError(null);
      } else {
        setError(reason(e, 'Could not upload. Please try again.'));
      }
    } finally {
      setBusy(false);
    }
  }

  const open: OsDocument | undefined = data?.documents.find((d) => d.id === openId);

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <OsHeader workspaceId={workspaceId} current="os-documents"
                title={open && data ? `Check what we read: ${typeLabel(open.doc_type, data.doc_types)}` : 'Your documents'} />
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {consent && !consent.agreed && !open && (
        <div className="mb-4">
          <ConsentCard consent={consent} refused={refused} onAgreed={loadConsent} onChanged={loadConsent} />
        </div>
      )}
      {data === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : open ? (
        <>
          <DocumentConfirm key={open.id} document={open} busy={busy} onBack={() => setOpenId(null)}
                           onConfirm={(values) => act(async () => {
                             await workspaceApi.confirmOsDocument(open.id, values);
                             setOpenId(null);
                           }, 'Could not save. Please try again.')} />
          <Button variant="ghost" className="mt-4 text-destructive" disabled={busy}
                  onClick={() => act(async () => {
                    await workspaceApi.deleteOsDocument(open.id);
                    setOpenId(null);
                  }, 'Could not delete. Please try again.')}>
            Delete this document
          </Button>
        </>
      ) : (
        <DocumentList documents={data.documents} findings={data.findings} docTypes={data.doc_types} busy={busy}
                      onOpen={(d) => setOpenId(d.id)}
                      onUpload={upload}
                      onResolve={(f, value) => act(() => workspaceApi.resolveOsFinding(f.id, value),
                                                   'Could not save your choice. Please try again.')}
                      onDelete={(d) => act(() => workspaceApi.deleteOsDocument(d.id),
                                           'Could not delete. Please try again.')} />
      )}
    </main>
  );
}
