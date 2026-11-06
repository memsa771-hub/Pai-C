'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import { asMyPlan, type MyPlan } from '@/lib/os-my-plan';

export interface MyPlanState {
  /** True only after a 200 answer. A 404, any error, still loading, or no provider all mean off: today's screens. */
  on: boolean;
  plan: MyPlan | null;
}

const OFF: MyPlanState = { on: false, plan: null };
const Ctx = createContext<MyPlanState>(OFF);

export const useMyPlan = () => useContext(Ctx);

/** Asks `GET /v1/os/plan` once. The student's screens learn the My plan part only from this answer. */
export function MyPlanProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<MyPlanState>(OFF);
  useEffect(() => {
    if (!OS_UI_ENABLED) return;
    let active = true;
    Promise.resolve().then(() => workspaceApi.getMyPlan()).then((got) => {
      const plan = asMyPlan(got);
      if (active && plan) setState({ on: true, plan });
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}
