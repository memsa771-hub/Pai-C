/** The Firebase web app, configured from public NEXT_PUBLIC_FIREBASE_* values.
 *
 * These are the web app's public identifiers (they ship in every bundle), not
 * secrets. NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST points local runs at the
 * Auth emulator. */
import { getApp, getApps, initializeApp } from 'firebase/app';
import { connectAuthEmulator, getAuth, type Auth } from 'firebase/auth';

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || '',
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN || '',
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID || '',
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || '',
};
const emulator = process.env.NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST || '';

let auth: Auth | null = null;

export function firebaseAuth(): Auth {
  if (auth) return auth;
  const app = getApps().length ? getApp() : initializeApp(config);
  auth = getAuth(app);
  if (emulator) connectAuthEmulator(auth, `http://${emulator}`, { disableWarnings: true });
  return auth;
}
