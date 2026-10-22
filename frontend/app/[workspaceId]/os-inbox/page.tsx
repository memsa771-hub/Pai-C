'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { InboxList } from '@/components/os/inbox-list';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsInboxItem } from '@/lib/os-inbox';
import { dateFactStatus, type FactStatus } from '@/lib/os-programmes';
import { swapPrompt, type OsNote } from '@/lib/os-self-serve';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

/** PAI OS student inbox: /<workspace>/os-inbox. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsInboxPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { user, idToken, loading } = usePaiAuth();
  const [items, setItems] = useState<OsInboxItem[] | null>(null);
  const [notes, setNotes] = useState<OsNote[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [factStatus, setFactStatus] = useState<Record<string, FactStatus | null>>({});

  const load = useCallback(async () => {
    try {
      setItems(await workspaceApi.getOsInbox());
      setError(null);
    } catch {
      setError('Could not load your next steps. Please try again.');
    }
    let years: number[] = [];
    try {  // the fact labels are extra: the inbox works without them
      const programmes = await workspaceApi.getOsProgrammes();
      setFactStatus(Object.fromEntries(programmes.map((p) => [p.ref, dateFactStatus(p)])));
      setNames((n) => ({ ...n, ...Object.fromEntries(programmes.map((p) => [p.ref, p.name])) }));
      years = [...new Set(programmes.map((p) => p.intake_year))];
    } catch {
      setFactStatus({});
    }
    try {  // Slice 4: eligibility changes, and the names of the programmes they suggest
      const found = await workspaceApi.getOsInboxNotes();
      setNotes(found);
      if (found.some((n) => n.payload.suggestions.length > 0) && years.length > 0) {
        const routes = await workspaceApi.getOsRoutes();
        const lists = await Promise.all(routes.flatMap((r) => years.map((y) => workspaceApi.getOsRouteProgrammes(r.key, y))));
        setNames((n) => ({ ...Object.fromEntries(lists.flat().map((p) => [p.ref, p.name])), ...n }));
      }
    } catch {
      setNotes([]);
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

  const complete = async (item: OsInboxItem, payload: Record<string, unknown> = {}) => {
    setBusyId(item.id);
    try {
      await workspaceApi.completeOsInboxItem(item.id, payload);
      await load();
    } catch {
      setError('That did not save. Please try again.');
    } finally {
      setBusyId(null);
    }
  };

  const swap = async (note: OsNote, inRef: string) => {
    const planId = note.payload.plan_id;
    if (planId === undefined) return;
    // The student's OK first (spec S4-D5): a swap removes the steps not yet started for the old programme.
    if (!window.confirm(swapPrompt(names[note.programme_ref] ?? note.programme_ref, names[inRef] ?? inRef))) return;
    try {
      await workspaceApi.swapOsProgramme(planId, note.programme_ref, inRef);
      await workspaceApi.readOsNote(note.id);
      await load();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '';
      const detail = msg.match(/"detail":"([^"]+)"/)?.[1];
      setError(detail ? `That swap could not be made: ${detail}.` : 'That swap did not go through. Please try again.');
    }
  };

  const readNote = async (note: OsNote) => {
    try {
      await workspaceApi.readOsNote(note.id);
      setNotes((ns) => ns.filter((n) => n.id !== note.id));
    } catch {
      setError('That did not save. Please try again.');
    }
  };

  if (!OS_UI_ENABLED) notFound();

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Your next steps</h1>
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <InboxList items={items} now={new Date()} onComplete={complete} busyId={busyId}
                   factStatus={factStatus} programmesHref={`/${workspaceId}/os-programmes`}
                   notes={notes} names={names} onSwap={swap} onReadNote={readNote} />
      )}
    </main>
  );
}
