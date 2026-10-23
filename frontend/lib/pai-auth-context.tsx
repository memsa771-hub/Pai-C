'use client';

/** Who is signed in, from Firebase Auth.
 *
 * Firebase keeps the sign-in (and syncs it across tabs); `onAuthStateChanged`
 * is the single source of truth. Email/password accounts that have not
 * verified their address are held at the "check your email" screen. Every API
 * call fetches a fresh ID token itself, so `idToken` here only says "signed in". */

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { User } from 'firebase/auth';
import { identify, resetIdentity } from './analytics';
import { workspaceApi } from './api';
import {
  AUTH_INVALID_EVENT, AUTH_UNVERIFIED_EVENT, FIREBASE_SESSION, onUserChange, signedInUser,
  signOut as firebaseSignOut, startSession,
} from './auth/service';

interface PaiUser {
  id: string;
  email: string;
  displayName: string;
  photoURL: string | null;
}

interface PaiAuthContextValue {
  user: PaiUser | null;
  /** FIREBASE_SESSION while a verified student is signed in, else null. */
  idToken: string | null;
  loading: boolean;
  isPaiDeployment: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  /** After a successful sign-in: tell the backend (device check) and enter the app. */
  applySession: () => Promise<void>;
}

const PAI_HOSTNAMES = ['app.placement-ai.com', 'placement-ai.com', 'localhost', 'workspace'];
export function isPaiHostname(hostname: string): boolean {
  const host = (hostname || '').toLowerCase().replace(/^www\./, '');
  return PAI_HOSTNAMES.includes(host) || host === '127.0.0.1' || host === '[::1]';
}

/** Pages a signed-out (or unverified) visitor may stay on. */
const PUBLIC_PATHS = ['/sign-in', '/sign-up', '/forgot-password'];
const isPublicPath = (path: string) => PUBLIC_PATHS.includes(path) || path.startsWith('/auth/');
export const VERIFY_EMAIL_PATH = '/auth/verify-email';

/** Email/password accounts must verify their address; Google accounts arrive verified. */
export function needsEmailVerification(user: User): boolean {
  return !user.emailVerified && user.providerData.some((p) => p.providerId === 'password');
}

const PaiAuthContext = createContext<PaiAuthContextValue | null>(null);
export function usePaiAuth() {
  const context = useContext(PaiAuthContext);
  if (!context) throw new Error('usePaiAuth must be used within PaiAuthProvider');
  return context;
}

function clearAccountBrowserState() {
  resetIdentity();
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('previews:') || key.startsWith('oa-read-') ||
          key.startsWith('oa:desktop:view:')) localStorage.removeItem(key);
    }
  } catch { /* storage may be disabled */ }
  workspaceApi.reset();
}

function hideSessionShield() {
  if (typeof document !== 'undefined') {
    const shield = document.getElementById('pai-session-shield');
    if (shield) shield.style.display = 'none';
  }
}

export function PaiAuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<PaiUser | null>(null);
  const [idToken, setIdToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isPaiDeployment, setIsPaiDeployment] = useState(false);
  const accountRef = useRef<string | null>(null);

  const clearSession = useCallback(() => {
    clearAccountBrowserState();
    accountRef.current = null;
    setUser(null);
    setIdToken(null);
    setLoading(false);
    hideSessionShield();
  }, []);

  const accept = useCallback((firebaseUser: User) => {
    if (accountRef.current && accountRef.current !== firebaseUser.uid) clearAccountBrowserState();
    accountRef.current = firebaseUser.uid;
    const email = firebaseUser.email || '';
    const displayName = firebaseUser.displayName || email;
    setUser({ id: firebaseUser.uid, email, displayName, photoURL: firebaseUser.photoURL });
    setIdToken(FIREBASE_SESSION);
    setLoading(false);
    hideSessionShield();
    identify(email, { email, display_name: displayName });
  }, []);

  const applySession = useCallback(async () => {
    const current = signedInUser();
    if (!current) throw new Error('Please sign in again.');
    await startSession();
    accept(current);
  }, [accept]);

  useEffect(() => {
    const hosted = isPaiHostname(window.location.hostname);
    setIsPaiDeployment(hosted);
    if (!hosted) { setLoading(false); return; }

    const unsubscribe = onUserChange((firebaseUser) => {
      const path = window.location.pathname;
      if (!firebaseUser) {
        clearSession();
        if (!isPublicPath(path)) window.location.replace('/sign-in');
        return;
      }
      if (needsEmailVerification(firebaseUser)) {
        clearSession();
        if (!isPublicPath(path)) window.location.replace(VERIFY_EMAIL_PATH);
        return;
      }
      accept(firebaseUser);
    });
    const onInvalid = () => { void firebaseSignOut(); };
    const onUnverified = () => { window.location.replace(VERIFY_EMAIL_PATH); };
    window.addEventListener(AUTH_INVALID_EVENT, onInvalid);
    window.addEventListener(AUTH_UNVERIFIED_EVENT, onUnverified);
    return () => {
      unsubscribe();
      window.removeEventListener(AUTH_INVALID_EVENT, onInvalid);
      window.removeEventListener(AUTH_UNVERIFIED_EVENT, onUnverified);
    };
  }, [accept, clearSession]);

  const signIn = useCallback(async () => {
    window.location.assign('/sign-in');
  }, []);

  const signOut = useCallback(async () => {
    await firebaseSignOut();
    clearSession();
  }, [clearSession]);

  return (
    <PaiAuthContext.Provider value={{
      user, idToken, loading, isPaiDeployment, signIn, signOut, applySession,
    }}>
      {children}
      <div
        id="pai-session-shield"
        aria-hidden="true"
        style={{ display: loading ? 'flex' : 'none' }}
        className="fixed inset-0 z-[9999] items-center justify-center bg-background"
      >
        <span className="text-sm text-muted-foreground">Opening Placement AI…</span>
      </div>
    </PaiAuthContext.Provider>
  );
}
