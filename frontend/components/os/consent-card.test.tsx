// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConsentCard } from './consent-card';
import { workspaceApi } from '@/lib/api';
import { consentCode, type OsConsent } from '@/lib/os-consent';

vi.mock('@/lib/api', () => ({ workspaceApi: { agreeOsConsent: vi.fn(), getOsConsent: vi.fn() } }));

// Fictional terms.
const TERMS: OsConsent = { version: 3, text: 'You can ask us to delete your data.', placeholder: false, agreed: false };
const conflict = (code: string) =>
  new Error(`API 409: ${JSON.stringify({ detail: { code, message: 'refused' } })}`);

// A block body: a function returned from beforeEach would run as its teardown.
beforeEach(() => { vi.mocked(workspaceApi.agreeOsConsent).mockResolvedValue(undefined); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe('ConsentCard', () => {
  it('shows the terms text, that this is a pilot, and one button', () => {
    render(<ConsentCard consent={TERMS} onAgreed={() => {}} />);
    expect(screen.getByText('This is a pilot')).toBeTruthy();
    expect(screen.getByText('You can ask us to delete your data.')).toBeTruthy();
    expect(screen.getAllByRole('button').map((b) => b.textContent)).toEqual(['I agree']);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('"I agree" sends the version shown, then tells the page', async () => {
    const onAgreed = vi.fn();
    render(<ConsentCard consent={TERMS} onAgreed={onAgreed} />);
    fireEvent.click(screen.getByRole('button', { name: 'I agree' }));
    await waitFor(() => expect(onAgreed).toHaveBeenCalledOnce());
    expect(workspaceApi.agreeOsConsent).toHaveBeenCalledExactlyOnceWith(3);
  });

  it('a refused start shows the request to agree first', () => {
    render(<ConsentCard consent={TERMS} refused onAgreed={() => {}} />);
    expect(screen.getByRole('alert').textContent).toBe('Please agree to the pilot terms first.');
  });

  it('a 409 because the terms changed asks again and reloads them', async () => {
    vi.mocked(workspaceApi.agreeOsConsent).mockRejectedValue(conflict('consent_version'));
    const onAgreed = vi.fn();
    const onChanged = vi.fn();
    render(<ConsentCard consent={TERMS} onAgreed={onAgreed} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole('button', { name: 'I agree' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Please agree to the pilot terms first.');
    expect(onChanged).toHaveBeenCalledOnce();
    expect(onAgreed).not.toHaveBeenCalled();
  });

  it('placeholder terms say they are not ready when refused', async () => {
    vi.mocked(workspaceApi.agreeOsConsent).mockRejectedValue(conflict('terms_not_set'));
    render(<ConsentCard consent={{ ...TERMS, placeholder: true }} onAgreed={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'I agree' }));
    expect((await screen.findByRole('alert')).textContent).toContain('not ready yet');
  });
});

describe('consentCode', () => {
  it('reads the code of a consent refusal only', () => {
    expect(consentCode(conflict('consent_needed'))).toBe('consent_needed');
    expect(consentCode(new Error('API 409: {"detail":"you already have a plan"}'))).toBeNull();
    expect(consentCode(new Error('API 422: {"detail":{"code":"consent_needed"}}'))).toBeNull();
    expect(consentCode('nope')).toBeNull();
  });
});

describe('consent calls', () => {
  it('get and agree use the OS consent endpoint', async () => {
    const { workspaceApi: real } = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === 'POST' ? new Response(null, { status: 204 })
        : new Response(JSON.stringify(TERMS), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    real.configure('ws-1', '', 'bearer-x');
    expect(await real.getOsConsent()).toEqual(TERMS);
    await real.agreeOsConsent(3);
    const [getUrl] = fetchMock.mock.calls[0];
    const [postUrl, postInit] = fetchMock.mock.calls[1];
    expect(getUrl).toContain('/v1/os/consent?network=ws-1');
    expect(postUrl).toContain('/v1/os/consent?network=ws-1');
    expect(postInit?.method).toBe('POST');
    expect(JSON.parse(String(postInit?.body))).toEqual({ version: 3 });
    vi.unstubAllGlobals();
  });
});
