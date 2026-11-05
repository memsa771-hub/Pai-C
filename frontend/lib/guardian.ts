// The guardian's one-time link (R-10): the public routes under /v1/guardian. The token is the only credential. It goes
// in the path and nowhere else (no query, no header, no storage), and no request sends a referrer.
import { API_URL } from '@/lib/config';

export type GuardianState = 'ok' | 'expired' | 'used' | 'stale';
export type GuardianMode = 'agree' | 'withdraw';
/** What a click on the button answers. */
export type GuardianAnswer = 'agreed' | 'withdrawn' | 'expired' | 'used' | 'stale';

export interface GuardianText {
  title: string;
  body: string[];
  agree_button: string;
}

export interface GuardianPage {
  state: GuardianState;
  text: GuardianText | null;
  student_first_name: string | null;
}

/** `busy`: too many requests from this address. `unavailable`: the connection is paused. `network`: anything else. */
export class GuardianError extends Error {
  constructor(public kind: 'busy' | 'unavailable' | 'network') {
    super(kind);
  }
}

async function call<T>(token: string, path: string, method: 'GET' | 'POST'): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/v1/guardian/${encodeURIComponent(token)}${path}`, {
      method,
      referrerPolicy: 'no-referrer',
      cache: 'no-store',
      credentials: 'omit',
    });
  } catch {
    throw new GuardianError('network');
  }
  if (res.status === 429) throw new GuardianError('busy');
  if (res.status === 409) throw new GuardianError('unavailable');
  if (!res.ok) throw new GuardianError('network');
  try {
    const json = await res.json();
    if (json.code !== 0) throw new GuardianError('network');
    return json.data as T;
  } catch (e) {
    throw e instanceof GuardianError ? e : new GuardianError('network');
  }
}

/**
 * What the page shows. Both e-mails link to the same /guardian/<token>: the first mail carries an agree token, the
 * confirmation mail a withdraw token. An agree lookup of a withdraw token answers `expired` (an unknown link looks
 * old), so then, and when agreeing is paused (409), the withdraw lookup decides. Neither lookup changes anything.
 */
export async function loadGuardianPage(token: string): Promise<{ mode: GuardianMode; page: GuardianPage }> {
  let agree: GuardianPage | null = null;
  try {
    agree = await call<GuardianPage>(token, '', 'GET');
  } catch (e) {
    if (!(e instanceof GuardianError) || e.kind !== 'unavailable') throw e;
  }
  if (agree && agree.state !== 'expired') return { mode: 'agree', page: agree };
  const withdraw = await call<GuardianPage>(token, '/withdraw', 'GET');
  if (agree && withdraw.state === 'expired') return { mode: 'agree', page: agree };
  return { mode: 'withdraw', page: withdraw };
}

/** The guardian presses the button. Only POST changes anything. */
export async function answerGuardian(token: string, mode: GuardianMode): Promise<GuardianAnswer> {
  const data = await call<{ state: GuardianAnswer }>(token, mode === 'agree' ? '/agree' : '/withdraw', 'POST');
  return data.state;
}
