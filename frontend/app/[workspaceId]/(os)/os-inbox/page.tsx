'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { OsHeader } from '@/components/os/os-header';
import { useMyPlan } from '@/components/os/my-plan-context';
import { NotInPlan } from '@/components/os/not-in-plan';
import { inPlan, pageTitle } from '@/lib/os-my-plan';
import { ChangesList } from '@/components/os/changes-list';
import { InboxList } from '@/components/os/inbox-list';
import { PausedBanner, ProposalCard } from '@/components/os/proposal-card';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsInboxItem } from '@/lib/os-inbox';
import { dateFactStatus, type FactStatus } from '@/lib/os-programmes';
import type { OsChanges, OsProposal } from '@/lib/os-replan';
import { changeMessage } from '@/lib/os-connect';
import { answerRefusal, withRequests, type OsRequest, type RequestWords } from '@/lib/os-requests';
import copy from '@/components/counselor/workspace/copy.json';
import { swapPrompt, type OsNote } from '@/lib/os-self-serve';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

/** PAI OS student inbox: /<workspace>/os-inbox. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsInboxPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { on, plan } = useMyPlan();  // P1-T9: the route's own page words; off, today's
  const outOfPlan = on && !inPlan(plan, 'inbox');  // a page the route does not have makes none of its own calls
  const { user, idToken, loading } = usePaiAuth();
  const [items, setItems] = useState<OsInboxItem[] | null>(null);
  const [notes, setNotes] = useState<OsNote[]>([]);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [factStatus, setFactStatus] = useState<Record<string, FactStatus | null>>({});
  const [changes, setChanges] = useState<OsChanges | null>(null);  // Slice 7: suggestions and what changed
  const [sent, setSent] = useState<OsProposal[]>([]);  // P1-T6: requests to the Counsellor and recent expired ones
  const [info, setInfo] = useState<string | null>(null);
  const [requests, setRequests] = useState<OsRequest[] | null>(null);  // P1-T8: null = no requests endpoint (today's inbox)

  const load = useCallback(async () => {
    let notesFound: OsNote[] = [];
    try {  // one request feeds the steps, the eligibility notes and the suggestions sent to the Counsellor
      const inbox = await workspaceApi.getOsInboxAll();
      setItems(inbox.items);
      setSent(inbox.proposals.filter((p) => p.status === 'requested' || p.status === 'expired'));
      notesFound = inbox.notes;
      setError(null);
    } catch {
      setSent([]);
      setError('Could not load your next steps. Please try again.');
    }
    try {  // P1-T8: what the plan asks of the student (extra: a 404 or an error leaves today's inbox)
      setRequests(await workspaceApi.getOsRequests());
    } catch {
      setRequests(null);
    }
    try {  // Slice 7: suggested changes and what changed (extra: the inbox works without them)
      const got = await workspaceApi.getOsChanges();
      setChanges(got);
      setNames((n) => ({ ...(got.names ?? {}), ...n }));  // a removed programme keeps its name in "What changed"
    } catch {
      setChanges(null);
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
      const found = notesFound;
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
    if (!OS_UI_ENABLED || loading || outOfPlan) return;
    if (!user) {
      goToSignIn();
      return;
    }
    // Placement AI: the bearer alone authorizes the call (no workspace token in the browser).
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    void load();
  }, [outOfPlan, loading, user, idToken, workspaceId, load]);

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

  const answerRequest = async (request: OsRequest, choice: string, value?: string | number) => {
    const question = { ref: request.ref ?? request.choices[0]?.ref ?? '', seen: request.seen ?? request.choices[0]?.seen ?? '' };
    setBusyId(request.task_id);
    setInfo(null);
    let message: string | null = null;
    let reload = true;  // the student looks at the list again: the step closed, or the question changed
    try {
      await workspaceApi.answerOsRequest(request.id, choice, question, value);
    } catch (e) {
      ({ text: message, reload } = answerRefusal(e, copy.connect.requests as RequestWords));
    } finally {
      setBusyId(null);
    }
    if (reload) await load();
    if (message) setError(message);  // after the reload, which clears the old error
  };

  const swap = async (note: OsNote, inRef: string) => {
    setInfo(null);
    const planId = note.payload.plan_id;
    if (planId === undefined) return;
    // The student's OK first (spec S4-D5): a swap removes the steps not yet started for the old programme.
    if (!window.confirm(swapPrompt(names[note.programme_ref] ?? note.programme_ref, names[inRef] ?? inRef))) return;
    try {
      const done = await workspaceApi.swapOsProgramme(planId, note.programme_ref, inRef);
      const sentLine = changeMessage(done, undefined, copy.connect);  // a Counsellor plan: the change was requested
      setInfo(sentLine?.text ?? null);
      await workspaceApi.readOsNote(note.id);
      await load();
    } catch (e) {
      const refusal = changeMessage(undefined, e, copy.connect);
      if (refusal) {
        setInfo(null);
        setError(refusal.text);
        return;
      }
      setInfo(null);
      const msg = e instanceof Error ? e.message : '';
      const detail = msg.match(/"detail":"([^"]+)"/)?.[1];
      setError(detail ? `That swap could not be made: ${detail}.` : 'That swap did not go through. Please try again.');
    }
  };

  const answer = async (id: number, accept: boolean) => {
    setBusyId(-id);
    setInfo(null);
    try {
      const done = await (accept ? workspaceApi.acceptOsProposal(id) : workspaceApi.declineOsProposal(id));
      await load();
      if (done.status === 'refused') setError(copy.connect.change.refused);  // not silent: the card is gone from the list
    } catch (e) {
      setInfo(null);
      const msg = e instanceof Error ? e.message : '';
      const detail = msg.match(/"detail":"([^"]+)"/)?.[1];
      setError(detail ? `That could not be done: ${detail}.` : 'That did not save. Please try again.');
      await load();
    } finally {
      setBusyId(null);
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

  if (outOfPlan) return <NotInPlan workspaceId={workspaceId} />;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <OsHeader workspaceId={workspaceId} current="os-inbox" title={pageTitle(plan, 'inbox', 'Your next steps')} />
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {info && <p role="status" className="mb-3 break-words text-sm text-muted-foreground">{info}</p>}
      {changes?.changes_paused && <PausedBanner />}
      {sent.length > 0 && (
        <section aria-label={copy.connect.change.sent_title} className="mb-6">
          <ul className="flex flex-col gap-2">
            {sent.map((p) => (
              <ProposalCard key={p.id} proposal={p} names={names} busy={false} onAccept={() => {}} onDecline={() => {}} />
            ))}
          </ul>
        </section>
      )}
      {changes && changes.pending.length > 0 && (
        <section aria-label="Suggested changes" className="mb-6">
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Suggested changes
          </h2>
          <ul className="flex flex-col gap-2">
            {changes.pending.map((p) => (
              <ProposalCard key={p.id} proposal={p} names={names} busy={busyId === -p.id}
                            onAccept={() => answer(p.id, true)} onDecline={() => answer(p.id, false)} />
            ))}
          </ul>
        </section>
      )}
      {items === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <InboxList items={withRequests(items, requests)} onAnswer={answerRequest} now={new Date()} onComplete={complete} busyId={busyId}
                   factStatus={factStatus} programmesHref={`/${workspaceId}/os-programmes`} basePath={`/${workspaceId}`}
                   notes={notes} names={names} onSwap={swap} onReadNote={readNote} />
      )}
      {changes && (
        <section aria-label="What changed" className="mt-8">
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            What changed
          </h2>
          <ChangesList changes={changes.changes} names={names} />
        </section>
      )}
    </div>
  );
}
