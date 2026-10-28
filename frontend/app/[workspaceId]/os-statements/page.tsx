'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { OsHeader } from '@/components/os/os-header';
import { StatementEditor } from '@/components/os/statement-editor';
import { StatementInterview } from '@/components/os/statement-interview';
import { StatementProgrammes } from '@/components/os/statement-programmes';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import {
  kindLabel, programmeNames, statusLabel, type OsInterview, type OsProgrammeRules, type OsStatement, type OsStatementKind,
} from '@/lib/os-statements';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

const POLL_MS = 4000; // while a draft is being written

/** The API's reason for a refused call; a 409 on a draft names the questions still to answer. */
function reason(e: unknown, fallback: string): string {
  const m = e instanceof Error ? /^API \d+: ([\s\S]+)$/.exec(e.message) : null;
  if (!m) return fallback;
  try {
    const detail = (JSON.parse(m[1]) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    const d = detail as { message?: string; missing?: string[] } | undefined;
    if (d?.missing?.length) return `Answer these questions first: ${d.missing.length} left.`;
    return d?.message ?? fallback;
  } catch {
    return m[1].length < 200 ? m[1] : fallback;
  }
}

/** PAI OS statements: /<workspace>/os-statements. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsStatementsPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [interview, setInterview] = useState<OsInterview | null>(null);
  const [statements, setStatements] = useState<OsStatement[] | null>(null);
  const [programmes, setProgrammes] = useState<OsProgrammeRules[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => Promise.all([workspaceApi.getOsInterview(), workspaceApi.getOsStatements()]).then(
    ([i, s]) => { setInterview(i); setStatements(s.statements); setProgrammes(s.programmes); setError(null); },
    (e) => setError(reason(e, 'Could not load your statements. Please try again.')),
  ), []);

  useEffect(() => {
    if (!OS_UI_ENABLED || loading) return;
    if (!user) {
      goToSignIn();
      return;
    }
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    load();
  }, [loading, user, idToken, workspaceId, load]);

  const writing = statements?.some((s) => s.status === 'drafting') ?? false;
  useEffect(() => {
    if (!writing) return;
    const t = setInterval(load, POLL_MS);
    return () => clearInterval(t);
  }, [writing, load]);

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

  const draft = (kind: OsStatementKind, programmeRef: string | null = null) =>
    act(() => workspaceApi.draftOsStatement(kind, programmeRef), 'Could not start the draft. Please try again.');
  const open = statements?.find((s) => s.id === openId);

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <OsHeader workspaceId={workspaceId} current="os-statements" title={open ? 'Your draft' : 'Your statement and CV'} />
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {interview === null || statements === null ? (
        <p className="text-sm text-muted-foreground">{error ? '' : 'Loading…'}</p>
      ) : open ? (
        <>
          <StatementEditor key={`${open.id}:${open.version?.number}`} statement={open} busy={busy}
                           names={programmeNames(programmes)}
                           onSave={(text) => act(() => workspaceApi.saveOsStatementText(open.id, text),
                                                 'Could not save. Please try again.')}
                           onRewrite={() => draft(open.kind, open.programme_ref)}
                           onApprove={(n) => act(() => workspaceApi.approveOsStatement(open.id, n),
                                                 'Could not approve. Please try again.')} />
          <Button variant="ghost" className="mt-4" onClick={() => setOpenId(null)}>Back</Button>
        </>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
            {statements.map((s) => (
              <button key={s.id} type="button" disabled={!s.version}
                      className="flex flex-wrap justify-between gap-2 text-left text-sm" onClick={() => setOpenId(s.id)}>
                <span className="break-words font-medium">{kindLabel(s.kind, s.programme_ref, programmeNames(programmes))}</span>
                <span className="text-muted-foreground">{statusLabel(s)}</span>
              </button>
            ))}
            <div className="flex flex-wrap gap-2">
              <Button disabled={busy || interview.missing.length > 0} onClick={() => draft('sop')}>Write my statement</Button>
              <Button variant="outline" disabled={busy || interview.missing.length > 0} onClick={() => draft('cv')}>Write my CV</Button>
            </div>
          </div>
          <StatementProgrammes programmes={programmes} statements={statements}
                               disabled={busy || interview.missing.length > 0}
                               onDraft={(ref) => draft('sop', ref)}
                               onPaste={(ref, rules) => act(() => workspaceApi.saveOsStatementRules(ref, rules),
                                                            'Could not save. Please try again.')} />
          <StatementInterview items={interview.questions} busy={busy}
                              onSave={(id, answer) => act(() => workspaceApi.saveOsAnswer(id, answer),
                                                          'Could not save your answer. Please try again.')} />
        </div>
      )}
    </main>
  );
}
