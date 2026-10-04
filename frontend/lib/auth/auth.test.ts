import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { OAUTH_PROVIDERS } from './oauth-providers';
import {
  buildOAuthAuthorizeUrl, consumePkceVerifier, requestPasswordReset,
  storePkceVerifier, signInWithPassword, signUpWithPassword,
  completePasswordReset,
} from '../supabase-auth';
import { authenticatedFetch, COOKIE_SESSION, establishSession, signOut } from './service';

const storage = new Map<string, string>();

beforeEach(() => {
  vi.stubGlobal('sessionStorage', {
    setItem: (key: string, value: string) => storage.set(key, value),
    getItem: (key: string) => storage.get(key) ?? null,
    removeItem: (key: string) => storage.delete(key),
  });
  vi.stubGlobal('window', { location: { origin: 'https://app.placement-ai.com' } });
});
afterEach(() => { storage.clear(); vi.unstubAllGlobals(); });

it('uses one Supabase OAuth registry and single-use PKCE for every social provider', async () => {
  expect(Object.keys(OAUTH_PROVIDERS)).toEqual(['google', 'github', 'linkedin']);
  for (const provider of Object.keys(OAUTH_PROVIDERS) as (keyof typeof OAUTH_PROVIDERS)[]) {
    const { url, codeVerifier } = await buildOAuthAuthorizeUrl(provider, 'https://app.placement-ai.com/auth/callback');
    const parsed = new URL(url, 'https://supabase.example.test');
    expect(parsed.pathname).toBe('/auth/v1/authorize');
    expect(parsed.searchParams.get('provider')).toBe(OAUTH_PROVIDERS[provider].supabaseProvider);
    expect(parsed.searchParams.get('code_challenge_method')).toBe('s256');
    expect(parsed.searchParams.get('code_challenge')).not.toBe(codeVerifier);
  }
  storePkceVerifier('once');
  expect(consumePkceVerifier()).toBe('once');
  expect(consumePkceVerifier()).toBeNull();
});

it('handles password sign-in, signup confirmation, and invalid credentials without leaking provider errors', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: 'jwt', refresh_token: 'refresh', user: { id: 'u', email: 'a@test' } }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ user: { id: 'u' } }) })
    .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ error: 'secret provider detail' }) });
  vi.stubGlobal('fetch', fetchMock);
  expect((await signInWithPassword('a@test', 'password')).accessToken).toBe('jwt');
  expect((await signUpWithPassword('a@test', 'password', 'student')).needsEmailConfirmation).toBe(true);
  const signupBody = JSON.parse(fetchMock.mock.calls[1][1].body);
  expect(signupBody.code_challenge_method).toBe('s256');
  expect(consumePkceVerifier()).toBeTruthy();
  await expect(signInWithPassword('a@test', 'wrong')).rejects.toThrow('Invalid email or password');
  expect(fetchMock.mock.calls[0][0]).toContain('/auth/v1/token?grant_type=password');
  expect(fetchMock.mock.calls[1][0]).toContain('/auth/v1/signup');
});

it('keeps recovery responses indistinguishable and rejects weak replacement passwords', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, status: 200 })
    .mockResolvedValueOnce({ ok: false, status: 400 });
  vi.stubGlobal('fetch', fetchMock);
  await expect(requestPasswordReset('registered@test')).resolves.toBeUndefined();
  await expect(requestPasswordReset('missing@test')).resolves.toBeUndefined();
  expect(fetchMock.mock.calls[0][0]).toContain('/auth/v1/recover');
  await expect(completePasswordReset('code', 'weak')).rejects.toThrow('stronger');
});

it('distinguishes provider and PAI network outages from invalid credentials', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
  await expect(signInWithPassword('a@test', 'password')).rejects.toThrow('temporarily unavailable');
  await expect(authenticatedFetch('/v1/account/workspace', {}, COOKIE_SESSION)).rejects.toThrow('temporarily unavailable');
});

it('uses the opaque cookie for app requests and revokes the PAI session on logout', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { user: { id: 'u', email: 'a@test' }, workspace: { slug: 'abc' } } }) })
    .mockResolvedValueOnce({ ok: true }) // best-effort provider device sign-out
    .mockResolvedValueOnce({ ok: true, json: async () => ({ data: {} }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ data: { revoked: true } }) });
  vi.stubGlobal('fetch', fetchMock);
  await establishSession({ accessToken: 'jwt', refreshToken: 'refresh', expiresAt: 0, user: { id: 'u', email: 'a@test', username: null } });
  await authenticatedFetch('/v1/account/workspace', {}, COOKIE_SESSION);
  await signOut();
  expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer jwt');
  expect(fetchMock.mock.calls[2][1].headers.Authorization).toBeUndefined();
  expect(fetchMock.mock.calls[2][1].credentials).toBe('include');
  expect(fetchMock.mock.calls[3][1].method).toBe('DELETE');
});
