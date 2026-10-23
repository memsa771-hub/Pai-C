/** The app-facing auth service on top of Firebase Auth.
 *
 * Firebase holds the sign-in; every API call carries a fresh Firebase ID token
 * as its Bearer. Our backend sends every account email (verification, reset,
 * new sign-in) through Resend, so nothing here asks Firebase to email anyone. */
import {
  applyActionCode, confirmPasswordReset, createUserWithEmailAndPassword, GoogleAuthProvider,
  onAuthStateChanged, signInWithEmailAndPassword, signInWithPopup, signOut as firebaseSignOut,
  verifyPasswordResetCode, type User,
} from 'firebase/auth';
import { API_URL } from '../config';
import { firebaseAuth } from '../firebase';

/** The context's "signed in" marker; the real bearer is fetched per request. */
export const FIREBASE_SESSION = 'firebase';
export const AUTH_INVALID_EVENT = 'pai:auth-invalid';
export const AUTH_UNVERIFIED_EVENT = 'pai:auth-unverified';

export interface PaiSession {
  user: { id: string; email: string; displayName: string };
  workspace: { workspaceId: string; slug: string };
  newDevice: boolean;
}

export class AuthUnavailable extends Error {}
export class AuthInvalid extends Error {}
/** Signed in with email and password, but the address is not verified yet. */
export class EmailNotVerified extends Error {}
/** The student closed the Google window; not an error worth showing. */
export class SignInCancelled extends Error {}

/** The signed-in Firebase user, if any. */
export function signedInUser(): User | null {
  return firebaseAuth().currentUser;
}

/** Follow sign-in changes (also across tabs); returns the unsubscribe. */
export function onUserChange(listener: (user: User | null) => void): () => void {
  return onAuthStateChanged(firebaseAuth(), listener);
}

/** Re-read the account after the student opened the link: true once verified
 * (with a refreshed token), false if not yet, null if nobody is signed in. */
export async function refreshVerification(): Promise<boolean | null> {
  const user = firebaseAuth().currentUser;
  if (!user) return null;
  await user.reload();
  if (!user.emailVerified) return false;
  await user.getIdToken(true);
  return true;
}

/** A fresh ID token for the signed-in student (Firebase refreshes it as needed). */
export async function currentIdToken(forceRefresh = false): Promise<string | null> {
  const user = firebaseAuth().currentUser;
  return user ? user.getIdToken(forceRefresh) : null;
}

export async function authenticatedFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const token = await currentIdToken();
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...options, cache: 'no-store',
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
    });
  } catch {
    throw new AuthUnavailable('Placement AI is temporarily unavailable');
  }
  if (response.status === 401) {
    if (typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_INVALID_EVENT));
    throw new AuthInvalid('Your session has expired. Please sign in again.');
  }
  if (response.status === 403) {
    const body = await response.clone().json().catch(() => null);
    if (body?.message === 'AUTH_EMAIL_NOT_VERIFIED') {
      if (typeof window !== 'undefined') window.dispatchEvent(new Event(AUTH_UNVERIFIED_EVENT));
      throw new EmailNotVerified('Please verify your email first.');
    }
  }
  return response;
}

async function data<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status >= 500) throw new AuthUnavailable('Placement AI is temporarily unavailable');
    if (response.status === 429) throw new AuthInvalid('Too many attempts. Please wait a little and try again.');
    const messages: Record<string, string> = {
      AUTH_INVALID_CREDENTIALS: 'Sign-in failed. Please try again.',
      AUTH_ACCOUNT_CONFLICT: 'This email is linked to another account. Contact support.',
    };
    throw new AuthInvalid(messages[body?.message] || 'Authentication failed. Please try again.');
  }
  return body.data as T;
}

const DEVICE_KEY = 'pai-device-id';

/** A random id for this browser, so the backend can tell a new device apart. */
function deviceId(): string {
  try {
    let id = localStorage.getItem(DEVICE_KEY);
    if (!id) { id = crypto.randomUUID(); localStorage.setItem(DEVICE_KEY, id); }
    return id;
  } catch {
    return crypto.randomUUID();
  }
}

/** After every sign-in: link the account and note this device. */
export async function startSession(): Promise<PaiSession> {
  return data<PaiSession>(await authenticatedFetch('/v1/auth/session', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ deviceId: deviceId() }),
  }));
}

/** Firebase error codes, in words a student can act on. */
function friendly(error: unknown, fallback: string): Error {
  const code = (error as { code?: string })?.code || '';
  const messages: Record<string, string> = {
    'auth/invalid-credential': 'That email or password does not match an account.',
    'auth/wrong-password': 'That email or password does not match an account.',
    'auth/user-not-found': 'That email or password does not match an account.',
    'auth/email-already-in-use': 'An account with this email already exists. Sign in instead.',
    'auth/weak-password': 'Password is too weak. Use 8+ characters with a mix of letters, numbers and symbols.',
    'auth/invalid-email': 'Enter a valid email address.',
    'auth/too-many-requests': 'Too many attempts. Please wait a little and try again.',
    'auth/user-disabled': 'This account has been turned off. Contact support.',
    'auth/network-request-failed': 'Placement AI is temporarily unavailable. Please try again.',
    'auth/account-exists-with-different-credential':
      'This email already signs in with a password. Sign in with your email and password.',
    'auth/popup-blocked': 'Your browser blocked the Google window. Allow pop-ups for this site and try again.',
    'auth/expired-action-code': 'This link has expired. Ask for a new one.',
    'auth/invalid-action-code': 'This link is invalid or has already been used. Ask for a new one.',
  };
  if (code === 'auth/network-request-failed') return new AuthUnavailable(messages[code]);
  return new AuthInvalid(messages[code] || fallback);
}

export async function signInWithPassword(email: string, password: string): Promise<User> {
  try {
    return (await signInWithEmailAndPassword(firebaseAuth(), email.trim(), password)).user;
  } catch (error) {
    throw friendly(error, 'Sign-in failed. Please check your details and try again.');
  }
}

/** Create the account and ask our backend to email the verification link. */
export async function signUpWithPassword(email: string, password: string): Promise<User> {
  let user: User;
  try {
    user = (await createUserWithEmailAndPassword(firebaseAuth(), email.trim(), password)).user;
  } catch (error) {
    throw friendly(error, 'We could not create your account. Please try again.');
  }
  await sendVerificationEmail();
  return user;
}

export async function signInWithGoogle(): Promise<User> {
  try {
    const provider = new GoogleAuthProvider();
    provider.setCustomParameters({ prompt: 'select_account' });
    return (await signInWithPopup(firebaseAuth(), provider)).user;
  } catch (error) {
    const code = (error as { code?: string })?.code;
    if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') {
      throw new SignInCancelled();
    }
    throw friendly(error, 'Could not finish Google sign-in. Please try again.');
  }
}

/** Ask for (another) verification email for the signed-in, unverified account. */
export async function sendVerificationEmail(): Promise<{ sent: boolean; alreadyVerified: boolean }> {
  return data(await authenticatedFetch('/v1/auth/send-verification', { method: 'POST' }));
}

/** Email a reset link; the answer is the same whether or not the account exists. */
export async function requestPasswordReset(email: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/auth/forgot-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim() }),
    });
  } catch {
    throw new AuthUnavailable('Placement AI is temporarily unavailable');
  }
  await data(response);
}

/** Apply a verifyEmail link; returns true when the signed-in student is now verified. */
export async function completeEmailVerification(code: string): Promise<boolean> {
  const auth = firebaseAuth();
  try {
    await applyActionCode(auth, code);
  } catch (error) {
    throw friendly(error, 'This link is invalid or has already been used. Ask for a new one.');
  }
  return (await refreshVerification()) === true;
}

/** Check a resetPassword link before asking for a new password; returns its email. */
export async function checkPasswordResetCode(code: string): Promise<string> {
  try {
    return await verifyPasswordResetCode(firebaseAuth(), code);
  } catch (error) {
    throw friendly(error, 'This link is invalid or has expired. Ask for a new one.');
  }
}

export async function completePasswordReset(code: string, password: string): Promise<void> {
  try {
    await confirmPasswordReset(firebaseAuth(), code, password);
  } catch (error) {
    throw friendly(error, 'We could not update your password. Please try again.');
  }
}

export async function signOut(): Promise<void> {
  await firebaseSignOut(firebaseAuth());
}
