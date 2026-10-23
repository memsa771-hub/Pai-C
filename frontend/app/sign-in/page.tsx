'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, FooterLink, GoogleButton, OrDivider, PasswordInput, SubmitButton, authInputClass, isEmail } from '@/components/auth/auth-shell';
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
    <AuthShell title={t('auth.signInTitle')} subtitle={t('auth.signInSubtitle')} links
      footer={<><span className="text-auth-muted">{t('auth.noAccount')}</span><FooterLink href="/sign-up">{t('auth.signUp')}</FooterLink></>}>
      <div className="flex flex-col gap-[var(--auth-gap)]">
        <GoogleButton label={t('auth.googleSignIn')} onClick={() => void google()} disabled={busy} />
        <OrDivider />
        <form onSubmit={submit} className="flex flex-col gap-[var(--auth-gap)]" noValidate>
          <div className="flex flex-col gap-[var(--auth-gap-fields)]">
            <AuthField label={t('auth.email')} error={field === 'email' ? error : null}>
              {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" autoCapitalize="none"
                spellCheck={false} placeholder={t('auth.emailPlaceholder')} required value={email}
                onChange={(e) => setEmail(e.target.value)} disabled={busy} />}
            </AuthField>
            <AuthField label={t('auth.password')} error={field === 'password' ? error : null}>
              {(props) => <PasswordInput {...props} autoComplete="current-password" placeholder={t('auth.passwordPlaceholder')} required value={password}
                onChange={(e) => setPassword(e.target.value)} disabled={busy} />}
            </AuthField>
            <Link href="/forgot-password" className="-my-3 self-end py-3 text-[13px] font-bold leading-[1.45] text-auth-blue hover:underline">
              {t('auth.forgot')}
            </Link>
          </div>
          {error && !field && <AuthAlert>{error}</AuthAlert>}
          <SubmitButton busy={busy} busyLabel={t('auth.signingIn')}>{t('auth.signIn')}</SubmitButton>
        </form>
      </div>
    </AuthShell>
  );
}
