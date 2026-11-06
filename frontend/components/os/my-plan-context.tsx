'use client';

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
}

const OFF: MyPlanState = { on: false, plan: null, refresh: () => {} };
export const MyPlanContext = createContext<MyPlanState>(OFF);

export const useMyPlan = () => useContext(MyPlanContext);

const READY_MS = 250;
const READY_TRIES = 40;

/** Asks `GET /v1/os/plan`. The student's screens learn the My plan part only from this answer.
 *
 * It asks only once sign-in has finished and the workspace API is set up for this workspace, as the OS pages do; "not
 * ready yet" is never an answer, so it cannot switch My plan off. Only a real 404 or error answer does.
 *
 * Until the answer arrives the screens show today's markup and swap when it says on (render, then swap). Holding the
 * render back until then would change what every screen shows with the part off, so it is not done. */
export function MyPlanProvider({ children }: { children: React.ReactNode }) {
  const { loading, user, idToken } = usePaiAuth();
  const [state, setState] = useState<{ on: boolean; plan: MyPlan | null }>({ on: false, plan: null });
  const alive = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => { alive.current = true; return () => { alive.current = false; clearTimeout(timer.current); }; }, []);

  const ask = useCallback((tries = READY_TRIES) => {
    clearTimeout(timer.current);
    if (!OS_UI_ENABLED || loading || !user) return;  // sign-in not finished: not an answer
    if (!workspaceApi.isConfigured?.()) {  // the workspace is not set up yet: wait, do not ask
      if (tries > 0) timer.current = setTimeout(() => ask(tries - 1), READY_MS);
      return;
    }
    Promise.resolve().then(() => workspaceApi.getMyPlan()).then((got) => {
      const plan = asMyPlan(got);
      if (alive.current) setState(plan ? { on: true, plan } : { on: false, plan: null });
    }).catch(() => { if (alive.current) setState({ on: false, plan: null }); });
  }, [loading, user]);

  useEffect(() => { ask(); }, [ask, idToken]);
  const refresh = useCallback(() => ask(), [ask]);
  return <MyPlanContext.Provider value={{ ...state, refresh }}>{children}</MyPlanContext.Provider>;
}
