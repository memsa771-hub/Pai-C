/** One application-facing auth service; Supabase details stay in its adapter. */
import { API_URL } from '../config';
import {
  signInWithPassword as providerSignIn,
  signUpWithPassword as providerSignUp,
  startOAuthRedirect,
  consumePkceVerifier,
  exchangeOAuthCode,
  requestPasswordReset as providerResetRequest,
  completePasswordReset as providerResetComplete,
  signOut as providerSignOut,
  type AuthSession,
} from '../supabase-auth';
import { signInWithUsername } from '../supabase-auth';
import type { OAuthProvider } from './oauth-providers';

export const COOKIE_SESSION = 'pai-cookie';
export const AUTH_INVALID_EVENT = 'pai:auth-invalid';

export interface PaiSession {
  user: { id: string; email: string; username: string | null; displayName: string };
  workspace: { workspaceId: string; slug: string };
  desktopToken?: string;
}

export class AuthUnavailable extends Error {}
export class AuthInvalid extends Error {}

export async function authenticatedFetch(path: string, options: RequestInit = {}, token?: string): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options, credentials: 'include', cache: 'no-store',
      headers: {
        ...(token && token !== COOKIE_SESSION ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch {
    throw new AuthUnavailable('Placement AI is temporarily unavailable');
  }
  if (response.status === 401 && path !== '/v1/auth/session') {
    if (typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_INVALID_EVENT));
    throw new AuthInvalid('Your session has expired. Please sign in again.');
  }
  return response;
}

async function data<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status >= 500) throw new AuthUnavailable('Placement AI is temporarily unavailable');
    const messages: Record<string, string> = {
      AUTH_EMAIL_CONFIRMATION_REQUIRED: 'Please confirm your email before signing in.',
      AUTH_SESSION_EXPIRED: 'Your session has expired. Please sign in again.',
      AUTH_SESSION_REVOKED: 'Your session has ended. Please sign in again.',
      AUTH_INVALID_CREDENTIALS: 'Sign-in failed. Please try again.',
      AUTH_ACCOUNT_CONFLICT: 'This email is linked to another account. Contact support.',
    };
    throw new AuthInvalid(messages[body?.message] || 'Authentication failed. Please try again.');
  }
  return body.data as T;
}

export async function establishSession(session: AuthSession, desktop = false,
  previousSession?: string | null): Promise<PaiSession> {
  const response = await authenticatedFetch('/v1/auth/session', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${session.accessToken}`,
      ...(desktop ? { 'X-PAI-Desktop': '1' } : {}),
      ...(desktop && previousSession ? { 'X-PAI-Previous-Session': previousSession } : {}),
    },
  });
  const result = await data<PaiSession>(response);
  // The provider credential has served its purpose. PAI's own revocable
  // session is now the only authorization authority for the web app.
  if (!desktop) void providerSignOut(session.accessToken);
  return result;
}

export async function restoreSession(token?: string): Promise<PaiSession> {
  return data<PaiSession>(await authenticatedFetch('/v1/auth/session', {}, token));
}

export async function signOut(token?: string): Promise<void> {
  const response = await authenticatedFetch('/v1/auth/session', { method: 'DELETE' }, token);
  if (response.status === 401) return; // already expired; the server has no live session
  await data(response);
}

export async function signInWithPassword(identifier: string, password: string): Promise<AuthSession> {
  return identifier.includes('@')
    ? providerSignIn(identifier.trim(), password)
    : signInWithUsername(identifier.trim(), password);
}

export const signUpWithPassword = providerSignUp;
export const signInWithOAuth = (provider: OAuthProvider) => startOAuthRedirect(provider);
export async function completeOAuth(code: string): Promise<AuthSession> {
  const verifier = consumePkceVerifier();
  if (!verifier) throw new AuthInvalid('Sign-in link is invalid or expired');
  return exchangeOAuthCode(code, verifier);
}
export const requestPasswordReset = providerResetRequest;
export const completePasswordReset = providerResetComplete;
