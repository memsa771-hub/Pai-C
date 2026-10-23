// Preview-only auth service: never contacts Firebase or the backend.
// The password "wrong" and the code "expired" fail so the harness can capture
// the error states.
const wait = () => new Promise((resolve) => setTimeout(resolve, 150));
export const FIREBASE_SESSION = 'firebase';
export const AUTH_INVALID_EVENT = 'pai:auth-invalid';
export const AUTH_UNVERIFIED_EVENT = 'pai:auth-unverified';
export class SignInCancelled extends Error {}
const student = { email: 'student@example.test', emailVerified: false };
export const signInWithPassword = async (_email: string, password: string) => {
  await wait(); if (password === 'wrong') throw new Error('That email or password does not match an account.'); return { ...student, emailVerified: true } as never;
};
export const signUpWithPassword = async () => { await wait(); return student as never; };
// The real call opens Google's window; the preview marks the URL and acts as if it was closed.
export const signInWithGoogle = async () => { location.hash = 'oauth-google'; throw new SignInCancelled(); };
export const startSession = async () => ({});
export const sendVerificationEmail = async () => { await wait(); return { sent: true, alreadyVerified: false }; };
export const refreshVerification = async () => false;
export const requestPasswordReset = async () => { await wait(); };
const expired = (code: string) => { if (code === 'expired') throw new Error('This link has expired. Ask for a new one.'); };
export const completeEmailVerification = async (code: string) => { await wait(); expired(code); return false; };
export const checkPasswordResetCode = async (code: string) => { await wait(); expired(code); return student.email; };
export const completePasswordReset = async () => { await wait(); };
export const signedInUser = () => null;
export const onUserChange = (listener: (user: typeof student | null) => void) => { setTimeout(() => listener(student)); return () => {}; };
export const signOut = async () => {};
export const authenticatedFetch = async (): Promise<Response> => { throw new Error('Network disabled in offline UI review'); };
