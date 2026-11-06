/**
 * Connection work (P1-T6): the answers the OS API gives when the Counsellor holds the route, and the adoption offer.
 * Types and pure helpers, free of React. Sentences come from the server (`note`, `status_note`, `text.*`); the few
 * fallbacks the screens need live in copy.json (`connect`). A missing key or null means "show nothing extra".
 */

/** POST /v1/os/plans/self with the Counsellor on: 202, no plan yet (R-09). */
export interface OsStartPending {
  state: 'preparing' | 'unchanged';
  decision_version: number;
  note?: string | null;
}

/** POST swap / DELETE programme on a Counsellor plan: 202, the change goes to the Counsellor (R-07). */
export interface OsChangeRequested {
  state: 'requested';
  proposal_id: number;
}

export function isStartPending(body: unknown): body is OsStartPending {
  const s = (body as { state?: unknown } | null)?.state;
  return s === 'preparing' || s === 'unchanged';
}

export function isChangeRequested(body: unknown): body is OsChangeRequested {
  return (body as { state?: unknown } | null)?.state === 'requested';
}

/** An API error ("API 409: {"detail":"choose_field_first","note":"…"}") as status, code and the server's note. */
export interface ApiRefusal {
  status: number | null;
  detail: string | null;
  note: string | null;
}

export function apiRefusal(err: unknown): ApiRefusal {
  const msg = err instanceof Error ? err.message : '';
  const m = /^API (\d{3}): ([\s\S]*)$/.exec(msg);
  if (!m) return { status: null, detail: null, note: null };
  let detail: string | null = null;
  let note: string | null = null;
  try {
    const body = JSON.parse(m[2]) as { detail?: unknown; note?: unknown };
    detail = typeof body.detail === 'string' ? body.detail : null;
    note = typeof body.note === 'string' && body.note.trim() ? body.note : null;
  } catch {
    /* a body that is not JSON: only the status is known */
  }
  return { status: Number(m[1]), detail, note };
}

export type AdoptionState = 'ready' | 'linking' | 'linked';

export interface AdoptionText {
  offer: string;
  agree: string;
  choose_field_first: string;
  too_many_places: string;
  linking: string;
}

/** GET /v1/roadmap/adoption. `text` is null while the owner has not approved the sentences. */
export interface Adoption {
  offer: boolean;
  state?: string;
  text?: AdoptionText | null;
  plan?: { plan_id: number; route_key: string; places: number };
}

/** POST /v1/roadmap/adoption: 200 `{state, decision_version}`. */
export interface AdoptionDone {
  state: 'linking' | 'linked';
  decision_version: number;
}

/** The `connect` block of copy.json: the fallbacks used where the server sends no sentence. */
export interface ConnectCopy {
  start: Record<string, string>;
  change: Record<string, string>;
  adoption: Record<string, string>;
}

/** A line the builder shows under the choices, with an optional link. */
export interface ConnectMessage {
  text: string;
  tone: 'info' | 'error';
  href?: string;
  linkLabel?: string;
}

/** What to show after a 202 from the builder (no plan yet). The server's note wins over the fallback. */
export function startPendingMessage(body: OsStartPending, copy: ConnectCopy): ConnectMessage {
  return { text: body.note || copy.start[body.state] || copy.start.preparing, tone: 'info' };
}

/** What to show when the builder was refused: 409 with a code and the server's note, or 503. Null: not a connection answer. */
export function startRefusalMessage(err: unknown, copy: ConnectCopy, journeyHref: string): ConnectMessage | null {
  const { status, detail, note } = apiRefusal(err);
  if (status === 503 && detail === 'counsellor_unavailable') return { text: copy.start.unavailable, tone: 'error' };
  if (status !== 409 || !detail) return null;
  if (detail === 'adopt_first') {
    return { text: note || copy.start.adopt_first, tone: 'error', href: journeyHref, linkLabel: copy.start.adopt_first_link };
  }
  if (detail === 'choose_field_first' || detail === 'too_many_places') {
    return { text: note || copy.start[detail], tone: 'error' };
  }
  return null;
}

/** What to show after a swap or remove on a Counsellor plan: 202 requested, or 409 `request_open`. Null: nothing special. */
export function changeMessage(result: unknown, err: unknown, copy: ConnectCopy): ConnectMessage | null {
  if (isChangeRequested(result)) return { text: copy.change.requested, tone: 'info' };
  if (err !== undefined && apiRefusal(err).detail === 'request_open') return { text: copy.change.request_open, tone: 'error' };
  return null;
}

/** The plain message for a refused adoption (POST 409 / 503), by its code. */
export function adoptionRefusalText(err: unknown, copy: ConnectCopy, text: AdoptionText | null | undefined): string {
  const { detail, status } = apiRefusal(err);
  if (detail === 'choose_field_first' || detail === 'too_many_places') return text?.[detail] || copy.start[detail];
  if (detail && copy.adoption[detail]) return copy.adoption[detail];
  if (status === 503) return copy.adoption.unavailable;
  return copy.adoption.other;
}
