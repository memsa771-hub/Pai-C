// The two auth endpoints workspace/backend provides beyond plain Supabase
// calls: attaching a unique username, and signing in by username without the
// client ever learning the resolved email. See workspace/backend/app/routers/auth.py.
import { API_URL } from './config';
import { authenticatedFetch } from './auth/service';

async function parseError(res: Response): Promise<Error> {
  const body = await res.json().catch(() => null);
  return new Error(body?.message || `API error (${res.status})`);
}

export async function isUsernameAvailable(username: string): Promise<boolean> {
  const res = await fetch(`${API_URL}/v1/auth/username-available`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) throw await parseError(res);
  const json = await res.json();
  return json.data?.available === true;
}

/** Attach a username to the caller's account. Idempotent for a username the
 * caller already owns. Throws with the backend's message on conflict/failure. */
export async function claimUsername(username: string): Promise<void> {
  const res = await authenticatedFetch('/v1/auth/claim-username', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) throw await parseError(res);
}
