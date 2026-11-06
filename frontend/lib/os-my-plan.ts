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

/** The OS's own generic page set (the `os-<key>` routes that exist). A page with another key has no screen. */
export const PAGE_KEYS = ['start', 'inbox', 'documents', 'programmes', 'statements', 'pack', 'visa'] as const;

/** An answer is a plan only when it has the shape; anything else reads as "the part is off". Each page needs a known
 * key and string label and title; a page that does not is dropped, the rest of the plan stays. */
export function asMyPlan(body: unknown): MyPlan | null {
  const b = body as Partial<MyPlan> | null;
  if (!b || typeof b !== 'object' || !Array.isArray(b.pages) || typeof b.state !== 'string') return null;
  const pages = (b.pages as unknown[]).filter((p): p is MyPlanPage => {
    const x = p as Partial<MyPlanPage> | null;
    return !!x && typeof x === 'object' && typeof x.key === 'string' && (PAGE_KEYS as readonly string[]).includes(x.key)
      && typeof x.label === 'string' && typeof x.title === 'string' && (x.noun == null || typeof x.noun === 'string');
  });
  return { ...(b as MyPlan), pages };
}

const page = (plan: MyPlan | null, key: string) => plan?.pages.find((p) => p.key === key);

/** The route's menu label for a page (`os-start` is page `start`); `fallback` when the plan has none. */
export const pageLabel = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.label ?? fallback;
export const pageTitle = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.title ?? fallback;
export const pageNoun = (plan: MyPlan | null, key: string, fallback: string) => page(plan, key)?.noun ?? fallback;
export const inPlan = (plan: MyPlan | null, key: string) => page(plan, key) !== undefined;

/** The four levels a fact can show (D-z8). `verified` exists in the copy but nothing produces it in P1 (R-25 is P2). */
export type FactLevel = 'verified' | 'confirmed' | 'not_confirmed' | 'estimated';

/** A fact's level from its own status: only `confirmed` is confirmed; an unknown status is never shown as settled. */
export function factLevel(status: string | null | undefined): FactLevel {
  if (status === 'confirmed') return 'confirmed';
  if (status === 'estimate') return 'estimated';
  return 'not_confirmed';
}

/** A dated step's level: estimated is estimated, provisional is not confirmed, a firm date is confirmed. */
export function stepLevel(step: { estimated?: boolean; provisional?: boolean }): FactLevel {
  if (step.estimated) return 'estimated';
  if (step.provisional) return 'not_confirmed';
  return 'confirmed';
}

/** The weaker of two levels (an estimate or a not-confirmed fact beats a confirmed step). */
export function weakerLevel(a: FactLevel, b: FactLevel): FactLevel {
  const rank: Record<FactLevel, number> = { not_confirmed: 0, estimated: 1, confirmed: 2, verified: 3 };
  return rank[a] <= rank[b] ? a : b;
}

/** The date a source was checked, as the endpoint gives it; null when it gives none (never guessed). */
export function checkedOn(plan: MyPlan | null, url: string | null | undefined): string | null {
  const at = url ? plan?.sources?.[url]?.checked_at : null;
  return typeof at === 'string' && at ? at : null;
}

/** A level, held down to "not confirmed" when the endpoint says the source itself is not confirmed. */
export function sourceLevel(plan: MyPlan | null, url: string | null | undefined, level: FactLevel): FactLevel {
  return url && plan?.sources?.[url]?.confirmed === false ? weakerLevel(level, 'not_confirmed') : level;
}

/** "6 Nov 2026" from an ISO date or timestamp (the date part only, in UTC). */
export function formatChecked(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }).format(d);
}
