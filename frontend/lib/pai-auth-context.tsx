'use client';

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { identify, resetIdentity } from './analytics';
import { desktopHost } from './desktop-host';
import { clearAuthSession } from './auth-session';
import { workspaceApi } from './api';
import {
  AUTH_INVALID_EVENT, AuthInvalid, AuthUnavailable, COOKIE_SESSION,
  establishSession, restoreSession, signOut as revokeSession,
} from './auth/service';
import type { AuthSession } from './supabase-auth';

interface PaiUser {
  id: string;
  email: string;
  displayName: string;
  photoURL: string | null;
}

interface PaiAuthContextValue {
  user: PaiUser | null;
  /** Web: cookie sentinel; Desktop: PAI application bearer held in memory. */
  idToken: string | null;
  loading: boolean;
  isPaiDeployment: boolean;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  applySession: (session: AuthSession) => Promise<void>;
}

const PAI_HOSTNAMES = ['app.placement-ai.com', 'placement-ai.com', 'localhost', 'workspace'];
export function isPaiHostname(hostname: string): boolean {
  const host = (hostname || '').toLowerCase().replace(/^www\./, '');
  return PAI_HOSTNAMES.includes(host) || host === '127.0.0.1' || host === '[::1]';
}

const PaiAuthContext = createContext<PaiAuthContextValue | null>(null);
export function usePaiAuth() {
  const context = useContext(PaiAuthContext);
  if (!context) throw new Error('usePaiAuth must be used within PaiAuthProvider');
  return context;
}

function clearAccountBrowserState() {
  clearAuthSession(); // migrate away from the old localStorage token format
  resetIdentity();
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith('previews:') || key.startsWith('oa-read-') ||
          key.startsWith('oa:desktop:view:')) localStorage.removeItem(key);
    }
    sessionStorage.removeItem('oa_pkce_verifier');
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
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelRef = useRef<BroadcastChannel | null>(null);
  const bearerRef = useRef<string | null>(null);
  const accountRef = useRef<string | null>(null);
  const validationRef = useRef(0);

  const clearSession = useCallback(() => {
    validationRef.current += 1;
    if (retryRef.current) clearTimeout(retryRef.current);
    clearAccountBrowserState();
    bearerRef.current = null;
    accountRef.current = null;
    setUser(null);
    setIdToken(null);
    setLoading(false);
    hideSessionShield();
  }, []);

  const accept = useCallback((session: {
    user: { id: string; email: string; displayName: string };
    desktopToken?: string;
  }, desktop = false) => {
    if (accountRef.current && accountRef.current !== session.user.id) clearAccountBrowserState();
    accountRef.current = session.user.id;
    const displayName = session.user.displayName || session.user.email;
    bearerRef.current = desktop ? session.desktopToken || null : COOKIE_SESSION;
    setUser({ id: session.user.id, email: session.user.email, displayName, photoURL: null });
    setIdToken(bearerRef.current);
    setLoading(false);
    hideSessionShield();
    identify(session.user.email, { email: session.user.email, display_name: displayName });
  }, []);

  const applySession = useCallback(async (providerSession: AuthSession) => {
    const session = await establishSession(providerSession);
    validationRef.current += 1;
    clearAuthSession();
    accept(session);
    channelRef.current?.postMessage('login');
  }, [accept]);

  const validate = useCallback(async () => {
    const validation = ++validationRef.current;
    setLoading(true);
    try {
      const session = await restoreSession();
      if (validation !== validationRef.current) return;
      accept(session);
    } catch (error) {
      if (validation !== validationRef.current) return;
      if (error instanceof AuthUnavailable) {
        // An outage says nothing about whether this cookie is still valid.
        retryRef.current = setTimeout(() => { void validate(); }, 30_000);
        return;
      }
      clearSession();
      if (window.location.pathname !== '/sign-in' &&
          window.location.pathname !== '/sign-up' &&
          window.location.pathname !== '/forgot-password' &&
          !window.location.pathname.startsWith('/auth/')) {
        window.location.replace('/sign-in');
      }
    }
  }, [accept, clearSession]);

  useEffect(() => {
    const hosted = isPaiHostname(window.location.hostname);
    setIsPaiDeployment(hosted);
    if (!hosted) { setLoading(false); return; }
    clearAuthSession();

    const host = desktopHost();
    if (host) {
      const adopt = async (handoff: { token: string; email: string; displayName?: string | null }) => {
        try {
          const providerSession: AuthSession = {
            accessToken: handoff.token, refreshToken: '', expiresAt: 0,
            user: { id: '', email: handoff.email, username: null },
          };
          const session = await establishSession(providerSession, true, bearerRef.current);
          accept(session, true);
        } catch { clearSession(); }
      };
      if (host.session) void adopt(host.session);
      else setLoading(false);
      const unsubscribe = host.onSession?.((next) => { void adopt(next); });
      return () => { unsubscribe?.(); };
    }

    void validate();
    const onPageHide = () => {
      const shield = document.getElementById('pai-session-shield');
      if (shield) shield.style.display = 'flex';
    };
    const onPageShow = () => { void validate(); };
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void validate();
    };
    const onInvalid = () => {
      clearSession();
      channelRef.current?.postMessage('logout');
      window.location.replace('/sign-in');
    };
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener(AUTH_INVALID_EVENT, onInvalid);
    if (typeof BroadcastChannel !== 'undefined') {
      const channel = new BroadcastChannel('pai-auth');
      channelRef.current = channel;
      channel.onmessage = (event) => {
        if (event.data === 'logout') {
          clearSession();
          window.location.replace('/sign-in');
        }
        if (event.data === 'login') void validate();
      };
    }
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
      window.removeEventListener('pagehide', onPageHide);
      window.removeEventListener('pageshow', onPageShow);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener(AUTH_INVALID_EVENT, onInvalid);
      channelRef.current?.close();
      channelRef.current = null;
    };
  }, [accept, clearSession, validate]);

  const signIn = useCallback(async () => {
    desktopHost()?.signIn();
  }, []);

  const signOut = useCallback(async () => {
    const host = desktopHost();
    await revokeSession(host ? bearerRef.current || undefined : undefined);
    channelRef.current?.postMessage('logout');
    clearSession();
    if (host) host.signOut();
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
