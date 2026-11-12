'use client';

import { use, useCallback, useState } from 'react';
import { notFound } from 'next/navigation';
import { CoverageReport } from '@/components/os/coverage-report';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { failingFromError, intakeLabel, type OsCoverage, type OsGateItem, type OsIntake } from '@/lib/os-coverage';

/**
 * PAI OS coverage dashboard: /<workspace>/os-admin/coverage (P2-T9, spec §4.9). Hidden unless NEXT_PUBLIC_OS_ENABLED=true.
 * The admin types their token for this visit: kept in memory only (never stored, never in a URL), sent in its own header.
 */
export default function OsCoveragePage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const [token, setToken] = useState('');
  const [intakes, setIntakes] = useState<OsIntake[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [report, setReport] = useState<OsCoverage | null>(null);
  const [refused, setRefused] = useState<OsGateItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadReport = useCallback(async (adminToken: string, id: number) => {
    setReport(await workspaceApi.getOsCoverage(adminToken, id));
  }, []);

  if (!OS_UI_ENABLED) notFound();

  async function signIn() {
    workspaceApi.configure(workspaceId, '');
    setBusy(true);
    setReport(null);
    let list: OsIntake[];
    try {
      list = await workspaceApi.getOsIntakes(token);
    } catch {
      setIntakes(null);
      setError('Could not load the intakes. Check the admin token and try again.');
      setBusy(false);
      return;
    }
    setIntakes(list);
    setError(null);
    try {
      if (list[0]) { setSelected(list[0].id); await loadReport(token, list[0].id); }
    } catch {
      // the token worked (the intakes came back): say that the report is what failed
      setError('The admin token works, but the coverage report could not be loaded. Pick the intake again to retry.');
    } finally {
      setBusy(false);
    }
  }

  async function pick(id: number) {
    setSelected(id);
    setRefused(null);
    setReport(null);  // never leave another intake's report on screen while this one loads or fails
    setBusy(true);
    try { await loadReport(token, id); setError(null); } catch { setError('The admin token works, but the coverage report could not be loaded.'); }
    finally { setBusy(false); }
  }

  async function makeCurrent() {
    if (selected == null) return;
    setBusy(true);
    try {
      await workspaceApi.makeOsIntakeCurrent(token, selected);
      setRefused(null);
      setIntakes(await workspaceApi.getOsIntakes(token));
      await loadReport(token, selected);
    } catch (e) {
      const failing = failingFromError(e);
      setRefused(failing);
      if (failing.length === 0) setError('Could not make the intake current. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Coverage and launch gate</h1>
      <form className="mb-4 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (token) void signIn(); }}>
        <input type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)}
               placeholder="Admin token" aria-label="Admin token"
               className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1 text-sm" />
        <Button size="sm" type="submit" disabled={!token || busy}>Show intakes</Button>
      </form>
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {intakes && intakes.length === 0 && <p className="text-sm text-muted-foreground">No intakes yet.</p>}
      {intakes && intakes.length > 0 && (
        <select aria-label="Intake" value={selected ?? ''} onChange={(e) => void pick(Number(e.target.value))}
                className="mb-4 w-full rounded-md border bg-background px-2 py-1 text-sm">
          {intakes.map((i) => <option key={i.id} value={i.id}>{intakeLabel(i)}</option>)}
        </select>
      )}
      {report && <CoverageReport report={report} busy={busy} refused={refused} onMakeCurrent={() => void makeCurrent()} />}
    </main>
  );
}
