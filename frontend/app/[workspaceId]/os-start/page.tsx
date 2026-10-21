'use client';

import { use, useCallback, useEffect, useState } from 'react';
import { notFound, useRouter } from 'next/navigation';
import { RouteBuilder } from '@/components/os/route-builder';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import {
  moveChoice,
  requestErrorText,
  toggleChoice,
  type OsEligibility,
  type OsRoute,
  type OsRouteProgramme,
} from '@/lib/os-self-serve';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

const TERM = 'winter'; // the intake term; routes do not list their terms yet (Slice 4 spec §4)

/** PAI OS self-serve start: /<workspace>/os-start. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsStartPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const router = useRouter();
  const { user, idToken, loading } = usePaiAuth();
  const [routes, setRoutes] = useState<OsRoute[]>([]);
  const [route, setRoute] = useState('');
  const [year, setYear] = useState(new Date().getFullYear() + 1);
  const [programmes, setProgrammes] = useState<OsRouteProgramme[] | null>(null);
  const [choices, setChoices] = useState<string[]>([]);
  const [openRef, setOpenRef] = useState<string | null>(null);
  const [open, setOpen] = useState<OsEligibility | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [requestSent, setRequestSent] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    if (!OS_UI_ENABLED || loading) return;
    if (!user) {
      goToSignIn();
      return;
    }
    // Placement AI: the bearer alone authorizes the call (no workspace token in the browser).
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    workspaceApi.getOsRoutes().then(
      (r) => { setRoutes(r); setRoute((cur) => cur || r[0]?.key || ''); },
      () => setError('Could not load the routes. Please try again.'),
    );
  }, [loading, user, idToken, workspaceId]);

  const loadProgrammes = useCallback(async () => {
    if (!route) return;
    try {
      setProgrammes(await workspaceApi.getOsRouteProgrammes(route, year));
      setError(null);
    } catch {
      setError('Could not load the programmes. Please try again.');
    }
  }, [route, year]);

  useEffect(() => { void loadProgrammes(); }, [loadProgrammes]);

  const openCard = async (ref: string | null) => {
    setOpenRef(ref);
    setOpen(null);
    if (ref) {
      try {
        setOpen(await workspaceApi.getOsEligibility(ref, route, year));
      } catch {
        setOpen(null);
      }
    }
  };

  const start = async () => {
    setStarting(true);
    try {
      await workspaceApi.startOsPlan(route, { term: TERM, year },
                                     choices.map((programme_ref, i) => ({ programme_ref, rank: i + 1 })));
      router.push(`/${workspaceId}/os-inbox`);
    } catch {
      setError('Your plan could not be started. Please check your choices and try again.');
    } finally {
      setStarting(false);
    }
  };

  const request = async (r: { university: string; name: string; url: string }) => {
    setRequestError(null);
    setRequestSent(null);
    try {
      const out = await workspaceApi.requestOsProgramme({ route, intake_year: year, ...r });
      setRequestSent(out.created
        ? 'Thank you. We are researching it; it will appear in the list once we have its facts.'
        : 'We already have this programme; it is in the list or being researched.');
      await loadProgrammes();
    } catch (e) {
      setRequestError(requestErrorText(e));
    }
  };

  if (!OS_UI_ENABLED) notFound();

  return (
    <main className="mx-auto w-full max-w-md px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold">Start your plan</h1>
      {error && <p role="alert" className="mb-3 break-words text-sm text-destructive">{error}</p>}
      {programmes === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <RouteBuilder routes={routes} route={route} onRoute={(k) => { setRoute(k); setChoices([]); }}
                      year={year} onYear={(y) => { setYear(y); setChoices([]); }} programmes={programmes}
                      choices={choices} onToggle={(ref) => setChoices((c) => toggleChoice(c, ref))}
                      onMove={(i, d) => setChoices((c) => moveChoice(c, i, d))} onStart={start} starting={starting}
                      openRef={openRef} openCard={open?.card ?? null} openSuggestions={open?.suggestions ?? []}
                      onOpen={openCard} onRequest={request} requestError={requestError} requestSent={requestSent} />
      )}
    </main>
  );
}
