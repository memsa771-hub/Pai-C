'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { PackView } from '@/components/os/pack';
import { PackDetails } from '@/components/os/pack-details';
import { VisaChoice, VisaFunds } from '@/components/os/visa-funds';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsPackFile } from '@/lib/os-packs';
import { asPack, type OsVisa } from '@/lib/os-visa';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

const POLL_MS = 4000; // while the visa file is being prepared

/** The API's reason for a refused call ("API 409: choose the programme…" -> the reason). */
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

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** PAI OS visa file: /<workspace>/os-visa (Slice 6b spec §5). Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsVisaPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [visa, setVisa] = useState<OsVisa | null>(null);
  const [details, setDetails] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => workspaceApi.getOsVisa().then(
    (d) => { setVisa(d); setError(null); },
    (e) => setError(reason(e, 'Could not load your visa file. Please try again.')),
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
  }, [loading, user, idToken, workspaceId, load]);

  const building = visa?.status === 'building';
  useEffect(() => {
    if (!building) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [building, load]);

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

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-4 px-4 py-6">
      <h1 className="break-words text-lg font-semibold">Your visa file</h1>
      {error && <p role="alert" className="break-words text-sm text-destructive">{error}</p>}
      {visa === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : details ? (
        <PackDetails rows={visa.data_sheet} busy={busy} onBack={() => setDetails(false)}
                     onSave={(fields) => act(async () => {
                       await workspaceApi.saveOsVisaDetails(fields);
                       setDetails(false);
                     }, 'Could not save your details. Please try again.')} />
      ) : (
        <>
          <VisaChoice visa={visa} busy={busy}
                      onChoose={(ref) => act(() => workspaceApi.saveOsVisaChoice({ programme_ref: ref }),
                                             'Could not save your choice. Please try again.')} />
          <VisaFunds key={visa.funds?.reduction ?? 0} funds={visa.funds} busy={busy}
                     onReduction={(amount) => act(() => workspaceApi.saveOsVisaChoice({ reduction: amount }),
                                                  'Could not save the amount. Please try again.')} />
          {visa.status !== 'no_choice' && (
            <PackView pack={asPack(visa)} busy={busy} noun="visa file"
                      notice="You apply and pay yourself. We never send anything for you."
                      onTick={(key, ticked) => act(() => workspaceApi.updateOsVisaItems(
                        ticked ? { tick: [key] } : { untick: [key] }), 'Could not save. Please try again.')}
                      onAdd={(label) => act(() => workspaceApi.updateOsVisaItems({ add: [{ label }] }),
                                            'Could not add it. Please try again.')}
                      onApprove={() => act(() => workspaceApi.approveOsVisa(visa.manifest_sha256 ?? ''),
                                           'Could not approve. Please try again.')}
                      onDownload={(f: OsPackFile) => act(async () => {
                        const got = await workspaceApi.downloadOsVisaFile(f.sha256);
                        save(got.blob, got.filename);
                      }, 'Could not download the file. Please try again.')}
                      onRebuild={() => act(() => workspaceApi.buildOsVisa(), 'Could not start it again. Please try again.')}
                      onDetails={() => setDetails(true)} />
          )}
        </>
      )}
    </main>
  );
}
