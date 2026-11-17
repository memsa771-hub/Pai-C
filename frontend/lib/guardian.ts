// The guardian's one-time link (R-10): the public routes under /v1/guardian. The token is the only credential. It goes
// in the path and nowhere else (no query, no header, no storage), and no request sends a referrer.
import { API_URL } from '@/lib/config';

export type GuardianState = 'ok' | 'expired' | 'used' | 'stale';
export type GuardianMode = 'agree' | 'withdraw';
/** What a click on the button answers. */
export type GuardianAnswer = 'agreed' | 'withdrawn' | 'expired' | 'used' | 'stale';

/** The approved wording from the API: `agree_button` on an agree page, `withdraw_button` on a withdraw page. */
export interface GuardianText {
  title: string;
  body: string[];
  agree_button?: string;
  withdraw_button?: string;
}

export interface GuardianPage {
  state: GuardianState;
  /** Which kind of link this is; absent while the connection is off (the API then answers `stale` and nothing else). */
  purpose?: GuardianMode;
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
 * confirmation mail a withdraw token. One lookup answers for whichever kind the token is (`purpose`), so a page load
 * counts once against the rate limit. The lookup changes nothing.
 */
export async function loadGuardianPage(token: string): Promise<{ mode: GuardianMode; page: GuardianPage }> {
  const page = await call<GuardianPage>(token, '', 'GET');
  return { mode: page.purpose ?? 'agree', page };
}

/** The guardian presses the button. Only POST changes anything. */
export async function answerGuardian(
  token: string,
  mode: GuardianMode,
): Promise<{ state: GuardianAnswer; confirmationSent: boolean }> {
  const data = await call<{ state: GuardianAnswer; confirmation_sent?: boolean }>(
    token, mode === 'agree' ? '/agree' : '/withdraw', 'POST');
  return { state: data.state, confirmationSent: data.confirmation_sent === true };
}
