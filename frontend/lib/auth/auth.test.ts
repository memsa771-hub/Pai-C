// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const firebase = vi.hoisted(() => ({
  currentUser: null as null | { getIdToken: ReturnType<typeof vi.fn>; reload?: ReturnType<typeof vi.fn>; emailVerified?: boolean },
  createUserWithEmailAndPassword: vi.fn(),
  signInWithEmailAndPassword: vi.fn(),
  signInWithPopup: vi.fn(),
}));

vi.mock('../firebase', () => ({ firebaseAuth: () => firebase }));
vi.mock('firebase/auth', () => ({
  applyActionCode: vi.fn(), confirmPasswordReset: vi.fn(), verifyPasswordResetCode: vi.fn(),
  onAuthStateChanged: vi.fn(), signOut: vi.fn(),
  createUserWithEmailAndPassword: firebase.createUserWithEmailAndPassword,
  signInWithEmailAndPassword: firebase.signInWithEmailAndPassword,
  signInWithPopup: firebase.signInWithPopup,
  GoogleAuthProvider: class { setCustomParameters() {} },
}));

import {
  AUTH_INVALID_EVENT, AUTH_UNVERIFIED_EVENT, AuthInvalid, AuthUnavailable, authenticatedFetch,
  EmailNotVerified, requestPasswordReset, SignInCancelled, signInWithGoogle, signInWithPassword,
  signUpWithPassword, startSession,
} from './service';

const fetchMock = vi.fn();
const ok = (data: unknown) => new Response(JSON.stringify({ code: 0, data }), { status: 200 });

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  firebase.currentUser = { getIdToken: vi.fn().mockResolvedValue('fresh-id-token') };
  localStorage.clear();
});
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it('sends a fresh Firebase ID token and no cookies', async () => {
  fetchMock.mockResolvedValue(ok({}));
  await authenticatedFetch('/v1/account/workspace');
  const [, init] = fetchMock.mock.calls[0];
  expect(init.headers.Authorization).toBe('Bearer fresh-id-token');
  expect(init.credentials).toBeUndefined();
  expect(firebase.currentUser!.getIdToken).toHaveBeenCalled();
});

it('a 401 signs out, a 403 for an unverified email goes to the verify screen', async () => {
  const invalid = vi.fn(), unverified = vi.fn();
  window.addEventListener(AUTH_INVALID_EVENT, invalid);
  window.addEventListener(AUTH_UNVERIFIED_EVENT, unverified);
  fetchMock.mockResolvedValueOnce(new Response('{}', { status: 401 }));
  await expect(authenticatedFetch('/v1/account/workspace')).rejects.toBeInstanceOf(AuthInvalid);
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ message: 'AUTH_EMAIL_NOT_VERIFIED' }), { status: 403 }));
  await expect(authenticatedFetch('/v1/account/workspace')).rejects.toBeInstanceOf(EmailNotVerified);
  expect(invalid).toHaveBeenCalledOnce();
  expect(unverified).toHaveBeenCalledOnce();
  fetchMock.mockRejectedValueOnce(new TypeError('offline'));
  await expect(authenticatedFetch('/v1/account/workspace')).rejects.toBeInstanceOf(AuthUnavailable);
});

it('every session call reports the same device id for this browser', async () => {
  fetchMock.mockImplementation(async () => ok({ newDevice: false }));
  await startSession();
  await startSession();
  const ids = fetchMock.mock.calls.map(([, init]) => JSON.parse(init.body).deviceId);
  expect(ids[0]).toBeTruthy();
  expect(ids[1]).toBe(ids[0]);
});

it('signing up creates the account and asks our backend to send the verification email', async () => {
  firebase.createUserWithEmailAndPassword.mockResolvedValue({ user: { uid: 'u1' } });
  fetchMock.mockResolvedValue(ok({ sent: true, alreadyVerified: false }));
  await signUpWithPassword(' new@example.test ', 'Better-pass1');
  expect(firebase.createUserWithEmailAndPassword).toHaveBeenCalledWith(firebase, 'new@example.test', 'Better-pass1');
  expect(fetchMock.mock.calls[0][0]).toMatch(/\/v1\/auth\/send-verification$/);
});

it('Google: a closed window is not an error, an email conflict is explained', async () => {
  firebase.signInWithPopup.mockRejectedValueOnce({ code: 'auth/popup-closed-by-user' });
  await expect(signInWithGoogle()).rejects.toBeInstanceOf(SignInCancelled);
  firebase.signInWithPopup.mockRejectedValueOnce({ code: 'auth/account-exists-with-different-credential' });
  await expect(signInWithGoogle()).rejects.toThrow('already signs in with a password');
});

it('wrong credentials read the same whichever part was wrong', async () => {
  firebase.signInWithEmailAndPassword.mockRejectedValue({ code: 'auth/invalid-credential' });
  await expect(signInWithPassword('a@example.test', 'nope')).rejects.toThrow('does not match an account');
});

it('a reset request posts only the email and needs no sign-in', async () => {
  firebase.currentUser = null;
  fetchMock.mockResolvedValue(ok({ sent: true }));
  await requestPasswordReset(' Someone@example.test ');
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/v1\/auth\/forgot-password$/);
  expect(JSON.parse(init.body)).toEqual({ email: 'Someone@example.test' });
  expect(init.headers.Authorization).toBeUndefined();
});
