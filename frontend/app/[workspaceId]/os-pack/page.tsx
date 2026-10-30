'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { OsHeader } from '@/components/os/os-header';
import { PackList, PackView } from '@/components/os/pack';
import { PackDetails } from '@/components/os/pack-details';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { programmeTitle, type OsPack, type OsPackFile } from '@/lib/os-packs';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

const POLL_MS = 4000; // while a pack is being prepared

/** The API's reason for a refused call ("API 409: the pack has changed…" -> the reason). */
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

/** PAI OS application packs: /<workspace>/os-pack. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsPackPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [packs, setPacks] = useState<OsPack[] | null>(null);
  const [openRef, setOpenRef] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => workspaceApi.getOsPacks().then(
    (d) => { setPacks(d.programmes); setError(null); },
    (e) => setError(reason(e, 'Could not load your application packs. Please try again.')),
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

  const building = packs?.some((p) => p.status === 'building') ?? false;
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

  const open = packs?.find((p) => p.programme_ref === openRef);

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <OsHeader workspaceId={workspaceId} current="os-pack" title={open ? programmeTitle(open) : 'Your application packs'} />
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {packs === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : open && details ? (
        <PackDetails rows={open.data_sheet} busy={busy} onBack={() => setDetails(false)}
                     onSave={(fields) => act(async () => {
                       await workspaceApi.saveOsPackDetails(fields);
                       setDetails(false);
                     }, 'Could not save your details. Please try again.')} />
      ) : open ? (
        <>
          <PackView pack={open} busy={busy}
                    onTick={(key, ticked) => act(() => workspaceApi.updateOsPackItems(open.programme_ref,
                      ticked ? { tick: [key] } : { untick: [key] }), 'Could not save. Please try again.')}
                    onAdd={(label) => act(() => workspaceApi.updateOsPackItems(open.programme_ref, { add: [{ label }] }),
                                          'Could not add it. Please try again.')}
                    onApprove={() => act(() => workspaceApi.approveOsPack(open.programme_ref, open.manifest_sha256 ?? ''),
                                         'Could not approve. Please try again.')}
                    onDownload={(f: OsPackFile) => act(async () => {
                      const got = await workspaceApi.downloadOsPackFile(open.programme_ref, f.sha256);
                      save(got.blob, got.filename);
                    }, 'Could not download the file. Please try again.')}
                    onRebuild={() => act(() => workspaceApi.buildOsPack(open.programme_ref),
                                         'Could not start it again. Please try again.')}
                    onDetails={() => setDetails(true)} />
          <Button variant="ghost" className="mt-4" onClick={() => setOpenRef(null)}>Back to all packs</Button>
        </>
      ) : (
        <PackList packs={packs} onOpen={(p) => setOpenRef(p.programme_ref)} />
      )}
    </main>
  );
}
