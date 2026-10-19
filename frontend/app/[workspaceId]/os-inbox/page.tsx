'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { InboxList } from '@/components/os/inbox-list';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsInboxItem } from '@/lib/os-inbox';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

/** PAI OS student inbox: /<workspace>/os-inbox. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsInboxPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [items, setItems] = useState<OsInboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await workspaceApi.getOsInbox());
      setError(null);
    } catch {
      setError('Could not load your next steps. Please try again.');
    }
  }, []);

  useEffect(() => {
    if (!OS_UI_ENABLED || loading) return;
    if (!user) {
      goToSignIn();
      return;
    }
    // Placement AI: the bearer alone authorizes the call (no workspace token in the browser).
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    void load();
  }, [loading, user, idToken, workspaceId, load]);

  const complete = async (item: OsInboxItem) => {
    setBusyId(item.id);
    try {
      await workspaceApi.completeOsInboxItem(item.id);
      await load();
    } catch {
      setError('That did not save. Please try again.');
    } finally {
      setBusyId(null);
    }
  };

  if (!OS_UI_ENABLED) notFound();

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Your next steps</h1>
      {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <InboxList items={items} now={new Date()} onComplete={complete} busyId={busyId} />
      )}
    </main>
  );
}
