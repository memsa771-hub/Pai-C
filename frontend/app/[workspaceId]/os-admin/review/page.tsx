'use client';

import { use, useCallback, useState } from 'react';
import { notFound } from 'next/navigation';
import { ReviewItem, type ReviewActions } from '@/components/os/review-item';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { kindLabel, openEvidence, type OsReviewDetail, type OsReviewItem, type OsReviewer } from '@/lib/os-review';

/**
 * PAI OS review queue: /<workspace>/os-admin/review (P2-T5, spec §4.5). Hidden unless NEXT_PUBLIC_OS_ENABLED=true.
 * The reviewer types their own token for this visit: kept in memory only (never stored, never in a URL) and sent in its
 * own header. It is not the admin token.
 */
export default function OsReviewPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const [token, setToken] = useState('');
  const [reviewer, setReviewer] = useState<OsReviewer | null>(null);
  const [items, setItems] = useState<OsReviewItem[] | null>(null);
  const [detail, setDetail] = useState<OsReviewDetail | null>(null);
  const [batch, setBatch] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadItems = useCallback(async (t: string) => {
    setItems(await workspaceApi.getOsReviewItems(t, 'open'));
  }, []);

  const guard = useCallback(async (work: () => Promise<void>, failure: string) => {
    setBusy(true);
    try {
      await work();
      setError(null);
    } catch (e) {
      const detailText = (e as { detail?: string }).detail;
      setError(detailText ? `${failure} ${detailText}` : failure);
    } finally {
      setBusy(false);
    }
  }, []);

  if (!OS_UI_ENABLED) notFound();

  async function signIn() {
    workspaceApi.configure(workspaceId, '');
    await guard(async () => {
      setReviewer(await workspaceApi.getOsReviewer(token));
      await loadItems(token);
    }, 'Could not sign in. Check your reviewer token.');
  }

  async function open(id: number) {
    await guard(async () => setDetail(await workspaceApi.getOsReviewItem(token, id)), 'Could not open the item.');
  }

  async function after(id: number, work: () => Promise<{ resolution: string | null }>) {
    await guard(async () => {
      const r = await work();
      setMessage(`Saved${r.resolution ? `: item closed (${r.resolution})` : ''}.`);
      await loadItems(token);
      setDetail(await workspaceApi.getOsReviewItem(token, id));
    }, 'Could not save.');
  }

  const actions: ReviewActions = {
    review: (id, body) => after(id, () => workspaceApi.postOsReview(token, id, body)),
    collect: (id, body) => after(id, () => workspaceApi.collectOsReview(token, id, body)),
    resolve: (id, outcome, note) => after(id, () => workspaceApi.resolveOsReview(token, id, outcome, note)),
    upload: async (id, file) => {
      const f = await workspaceApi.uploadOsReviewEvidence(token, id, file);
      setDetail(await workspaceApi.getOsReviewItem(token, id));
      return f.id;
    },
    openFile: (fileId) => {
      void guard(async () => {
        const blob = await workspaceApi.getOsReviewFile(token, fileId);
        const name = detail?.files.find((f) => f.id === fileId)?.filename ?? 'evidence';
        openEvidence(blob, name, {
          createObjectURL: (b) => URL.createObjectURL(b),
          revokeObjectURL: (u) => setTimeout(() => URL.revokeObjectURL(u), 10_000),
          open: (u) => { window.open(u, '_blank', 'noopener'); },
          download: (u, n) => {
            const a = document.createElement('a');
            a.href = u;
            a.download = n;
            a.rel = 'noopener';
            a.click();
          },
        });
      }, 'Could not open the file.');
    },
  };

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Review queue</h1>
      <form className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (token) void signIn(); }}>
        <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
               placeholder="Reviewer token" aria-label="Reviewer token"
               className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm" />
        <Button size="sm" type="submit" disabled={!token || busy}>Sign in</Button>
      </form>
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {message && <p role="status" className="mb-3 text-sm">{message}</p>}
      {reviewer && (
        <p className="mb-3 text-sm text-muted-foreground">
          Signed in as {reviewer.display_name} ({reviewer.role}, {reviewer.kind}).
        </p>
      )}
      {reviewer && (
        <form className="mb-4 flex flex-wrap gap-2 text-sm" aria-label="Attest a batch"
              onSubmit={(e) => { e.preventDefault(); if (batch.trim()) void guard(async () => {
                const r = await workspaceApi.attestOsReviewBatch(token, batch.trim());
                setMessage(r.new ? `You attested batch ${r.batch_ref}.` : `You had already attested batch ${r.batch_ref}.`);
              }, 'Could not attest.'); }}>
          <input value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="Batch reference" aria-label="Batch reference"
                 className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1" />
          <Button size="sm" variant="outline" type="submit" disabled={!batch.trim() || busy}>I checked the rows of this batch</Button>
        </form>
      )}
      {items !== null && (
        items.length === 0 ? <p className="text-sm text-muted-foreground">Nothing waits for review.</p> : (
          <ul aria-label="Open items" className="mb-6 flex flex-col gap-2 text-sm">
            {items.map((i) => (
              <li key={i.id}>
                <button type="button" onClick={() => void open(i.id)}
                        className="w-full rounded-xl border bg-card p-3 text-left break-words">
                  <span className="font-medium">{kindLabel(i.kind)}</span>{i.field ? ` · ${i.field}` : ''}
                  {i.intake_year ? ` · ${i.intake_year}` : ''}
                  {i.summary ? <span className="block text-xs text-muted-foreground">{i.summary}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        )
      )}
      {detail && reviewer && <ReviewItem detail={detail} reviewer={reviewer} busy={busy} actions={actions} />}
    </main>
  );
}
