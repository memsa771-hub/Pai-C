'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, OAuthButtons, PasswordInput, SubmitButton, authInputClass } from '@/components/auth/auth-shell';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { signInWithPassword, signInWithOAuth } from '@/lib/auth/service';
import type { OAuthProvider } from '@/lib/auth/oauth-providers';
import { desktopHost } from '@/lib/desktop-host';
import { useT } from '@/lib/i18n';

export default function SignInPage() {
  const router = useRouter();
  const t = useT();
  const { applySession, user, loading } = usePaiAuth();
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace('/');
  }, [loading, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const session = await signInWithPassword(identifier.trim(), password);
      await applySession(session);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('auth.errorSignIn'));
    } finally {
      setBusy(false);
    }
  };

  const oauth = async (provider: OAuthProvider) => {
    setError(null);
    // Inside the desktop app's embedded view, OAuth can't complete on this
    // origin (a custom Electron scheme Supabase can't redirect back to) —
    // delegate to the launcher's own native sign-in, which runs the browser
    // round trip outside this view.
    const host = desktopHost();
    if (host) { host.signIn(); return; }
    try {
      await signInWithOAuth(provider);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('auth.errorOAuth'));
    }
  };

  return (
    <AuthShell title={t('auth.signInTitle')} subtitle={t('auth.signInSubtitle')}
      footer={<>{t('auth.noAccount')}{' '}<Link href="/sign-up" className="font-semibold text-brand-ink underline-offset-4 hover:underline">{t('auth.signUp')}</Link></>}>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <AuthField label={t('auth.identifier')}>
          {(field) => <Input {...field} className={authInputClass} autoComplete="username" autoCapitalize="none" spellCheck={false}
            autoFocus required value={identifier} onChange={(e) => setIdentifier(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.password')}>
          {(field) => <PasswordInput {...field} autoComplete="current-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        <div className="-mt-1 text-right text-sm">
          <Link href="/forgot-password" className="inline-flex min-h-11 items-center font-semibold text-brand-ink underline-offset-4 hover:underline">{t('auth.forgot')}</Link>
        </div>
        {error && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.signingIn')} disabled={!identifier.trim() || !password}>{t('auth.signIn')}</SubmitButton>
      </form>
      <OAuthButtons onSelect={(provider) => void oauth(provider)} disabled={busy} />
    </AuthShell>
  );
}
