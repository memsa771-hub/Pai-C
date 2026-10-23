'use client';

import { use, useCallback, useState } from 'react';
import { notFound } from 'next/navigation';
import { SupportList } from '@/components/os/support-list';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsSupportCase } from '@/lib/os-replan';

/**
 * PAI OS admin support inbox: /<workspace>/os-admin/support (Slice 7 spec §5). Hidden unless
 * NEXT_PUBLIC_OS_ENABLED=true. The admin types their token for this visit: it is kept in memory only (never stored,
 * never in a URL) and sent in its own header.
 */
export default function OsSupportPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const [token, setToken] = useState('');
  const [cases, setCases] = useState<OsSupportCase[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (adminToken: string) => {
    workspaceApi.configure(workspaceId, '');
    try {
      setCases(await workspaceApi.getOsSupportCases(adminToken, 'open'));
      setError(null);
    } catch {
      setCases(null);
      setError('Could not load the cases. Check the admin token and try again.');
    }
  }, [workspaceId]);

  if (!OS_UI_ENABLED) notFound();

  async function resolve(id: number, note: string, unpause: boolean) {
    setBusy(true);
    try {
      await workspaceApi.resolveOsSupportCase(token, id, note, unpause);
      await load(token);
    } catch {
      setError('Could not resolve the case. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Support inbox</h1>
      <form className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (token) void load(token); }}>
        <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
               placeholder="Admin token" aria-label="Admin token"
               className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm" />
        <Button size="sm" type="submit" disabled={!token}>Show cases</Button>
      </form>
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {cases !== null && <SupportList cases={cases} busy={busy} onResolve={resolve} />}
    </main>
  );
}
