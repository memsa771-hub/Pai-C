/** My plan (P1-T9, R-50..R-53): the student's plan as `GET /v1/os/plan` answers it. Pure helpers; every word on a
 * page comes from the route's own data, so nothing here names a country, a body or a document. */

export interface MyPlanPage {
  key: string;
  label: string;
  title: string;
  noun: string | null;
}

export interface MyPlanSource {
  checked_at: string;
  confirmed: boolean;
}

export interface MyPlan {
  state: string;
  source: string | null;
  plan_id: number | null;
  route_key: string | null;
  abroad: boolean | null;
  pages: MyPlanPage[];
  sources: Record<string, MyPlanSource>;
}

/** An answer is a plan only when it has the shape; anything else reads as "the part is off". */
export function asMyPlan(body: unknown): MyPlan | null {
  const b = body as Partial<MyPlan> | null;
  return b && typeof b === 'object' && Array.isArray(b.pages) && typeof b.state === 'string' ? (b as MyPlan) : null;
}

const page = (plan: MyPlan | null, key: string) => plan?.pages.find((p) => p.key === key);

/** The route's menu label for a page (`os-start` is page `start`); `fallback` when the plan has none. */
export const pageLabel = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.label ?? fallback;
export const pageTitle = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.title ?? fallback;
export const pageNoun = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.noun ?? fallback;
export const inPlan = (plan: MyPlan | null, key: string) => page(plan, key) !== undefined;
