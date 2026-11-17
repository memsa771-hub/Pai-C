'use client';

import { useParams } from 'next/navigation';
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { asMyPlan, type MyPlan } from '@/lib/os-my-plan';
import { usePaiAuth } from '@/lib/pai-auth-context';

export interface MyPlanState {
  /** True only after a 200 answer. A 404, any error, still loading, or no provider all mean off: today's screens. */
  on: boolean;
  plan: MyPlan | null;
  /** Asks again (after a choice, an adoption or a start). Does nothing outside the provider. */
  refresh: () => void;
  /** Whether the stage is open for the start page (`osOpenAt`): the shell tells it; the builder stays reachable before a choice. */
  startOpen?: boolean;
  setStartOpen?: (open: boolean) => void;
}

const OFF: MyPlanState = { on: false, plan: null, refresh: () => {}, startOpen: false, setStartOpen: () => {} };
export const MyPlanContext = createContext<MyPlanState>(OFF);

export const useMyPlan = () => useContext(MyPlanContext);

const READY_MS = 250;
const READY_TRIES = 40;
const POLL_MS = 2000;
const POLL_FOR_MS = 60_000;

/** Asks `GET /v1/os/plan`. The student's screens learn the My plan part only from this answer.
 *
 * It asks only once sign-in has finished and the workspace API is set up for this workspace, as the OS pages do; "not
 * ready yet" is never an answer, so it cannot switch My plan off. Only a real 404 or error answer does.
 *
 * The OS applies a choice a little later, so after `refresh()` (a choice, an adoption, a start) an `empty` answer is
 * asked again every 2 s for at most 60 s, until the plan is no longer empty. It also asks again when the window gets
 * focus, and starts again from OFF when the workspace changes.
 *
 * Until the answer arrives the screens show today's markup and swap when it says on (render, then swap). Holding the
 * render back until then would change what every screen shows with the part off, so it is not done. */
export function MyPlanProvider({ children }: { children: React.ReactNode }) {
  const { loading, user, idToken } = usePaiAuth();
  const workspaceId = useParams<{ workspaceId: string }>()?.workspaceId;
  const [state, setState] = useState<{ on: boolean; plan: MyPlan | null }>({ on: false, plan: null });
  const [startOpen, setStartOpen] = useState(false);
  const alive = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pollUntil = useRef(0);
  const generation = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; clearTimeout(timer.current); }; }, []);

  const ask = useCallback((tries = READY_TRIES) => {
    clearTimeout(timer.current);
    if (!OS_UI_ENABLED || loading || !user) return;  // sign-in not finished: not an answer
    if (!workspaceApi.isConfigured?.()) {  // the workspace is not set up yet: wait, do not ask
      if (tries > 0) timer.current = setTimeout(() => ask(tries - 1), READY_MS);
      return;
    }
    const mine = generation.current;
    Promise.resolve().then(() => workspaceApi.getMyPlan()).then((got) => {
      if (!alive.current || mine !== generation.current) return;  // another workspace has taken over
      const plan = asMyPlan(got);
      setState(plan ? { on: true, plan } : { on: false, plan: null });
      if (plan?.state === 'empty' && Date.now() < pollUntil.current) timer.current = setTimeout(() => ask(), POLL_MS);
      else pollUntil.current = 0;
    }).catch(() => { if (alive.current && mine === generation.current) setState({ on: false, plan: null }); });
  }, [loading, user]);

  useEffect(() => {  // another workspace: start from OFF, as on first load
    generation.current += 1;
    pollUntil.current = 0;
    setState({ on: false, plan: null });
  }, [workspaceId]);
  useEffect(() => { ask(); }, [ask, idToken, workspaceId]);
  useEffect(() => {
    const onFocus = () => ask();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [ask]);
  const refresh = useCallback(() => { pollUntil.current = Date.now() + POLL_FOR_MS; ask(); }, [ask]);
  return <MyPlanContext.Provider value={{ ...state, refresh, startOpen, setStartOpen }}>{children}</MyPlanContext.Provider>;
}
