'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, FooterLink, GoogleButton, PasswordInput, SubmitButton, authInputClass, isEmail } from '@/components/auth/auth-shell';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { signInWithPassword, signInWithOAuth } from '@/lib/auth/service';
import { desktopHost } from '@/lib/desktop-host';
import { useT } from '@/lib/i18n';

export default function SignInPage() {
  const router = useRouter();
  const t = useT();
  const { applySession, user, loading } = usePaiAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [field, setField] = useState<'email' | 'password' | null>(null);

  useEffect(() => {
    if (!loading && user) router.replace('/');
  }, [loading, user, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); setField(null);
    if (!isEmail(email)) { setError(t('auth.errorEmail')); setField('email'); return; }
    if (!password) { setError(t('auth.errorPasswordRequired')); setField('password'); return; }
    setBusy(true);
    try {
      const session = await signInWithPassword(email.trim(), password);
      await applySession(session);
      router.replace('/');
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('auth.errorSignIn'));
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setError(null);
    // Inside the desktop app's embedded view, OAuth can't complete on this
    // origin (a custom Electron scheme Supabase can't redirect back to) —
    // delegate to the launcher's own native sign-in, which runs the browser
    // round trip outside this view.
    const host = desktopHost();
    if (host) { host.signIn(); return; }
    try {
      await signInWithOAuth('google');
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t('auth.errorOAuth'));
    }
  };

  return (
    <AuthShell title={t('auth.signInTitle')}
      footer={<>{t('auth.noAccount')}{' '}<FooterLink href="/sign-up">{t('auth.signUp')}</FooterLink></>}>
      <GoogleButton label={t('auth.googleSignIn')} onClick={() => void google()} disabled={busy} />
      <form onSubmit={submit} className="mt-6 grid gap-4" noValidate>
        <AuthField label={t('auth.email')} error={field === 'email' ? error : null}>
          {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" autoCapitalize="none"
            spellCheck={false} placeholder={t('auth.emailPlaceholder')} required value={email}
            onChange={(e) => setEmail(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.password')} error={field === 'password' ? error : null}>
          {(props) => <PasswordInput {...props} autoComplete="current-password" placeholder="•••••••" required value={password}
            onChange={(e) => setPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        <div className="-mt-2 text-right">
          <Link href="/forgot-password" className="inline-flex min-h-11 items-center text-xs font-medium text-auth-muted underline-offset-4 hover:text-auth-ink hover:underline">
            {t('auth.forgot')}
          </Link>
        </div>
        {error && !field && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.signingIn')}>{t('auth.signIn')}</SubmitButton>
      </form>
    </AuthShell>
  );
}
