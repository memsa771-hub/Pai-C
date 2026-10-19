'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Loader2, MailCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, AuthStatus, OAuthButtons, PasswordInput, SubmitButton, authInputClass } from '@/components/auth/auth-shell';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { signUpWithPassword, signInWithOAuth } from '@/lib/auth/service';
import type { OAuthProvider } from '@/lib/auth/oauth-providers';
import { claimUsername, isUsernameAvailable } from '@/lib/auth-api';
import { registrationPasswordError } from '@/lib/password-policy';
import { desktopHost } from '@/lib/desktop-host';
import { useT } from '@/lib/i18n';

type FieldError = 'username' | 'password' | 'confirm' | null;

export default function SignUpPage() {
  const router = useRouter();
  const t = useT();
  const { applySession, idToken } = usePaiAuth();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [field, setField] = useState<FieldError>(null);
  const [busy, setBusy] = useState(false);
  const [checkEmail, setCheckEmail] = useState(false);

  useEffect(() => {
    if (idToken) router.replace('/');
  }, [idToken, router]);

  const fail = (message: string, which: FieldError = null) => { setError(message); setField(which); };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    fail('', null); setError(null);

    const normalizedUsername = username.trim().toLowerCase();
    if (!/^[a-z0-9_-]{3,32}$/.test(normalizedUsername)) return fail(t('auth.errorUsername'), 'username');
    if (registrationPasswordError(password)) return fail(t('auth.errorWeakPassword'), 'password');
    if (password !== confirmPassword) return fail(t('auth.errorMismatch'), 'confirm');

    setBusy(true);
    try {
      if (!(await isUsernameAvailable(normalizedUsername))) {
        fail(t('auth.errorUsernameTaken'), 'username');
        return;
      }
      const { session, needsEmailConfirmation } = await signUpWithPassword(
        email.trim(),
        password,
        normalizedUsername,
      );
      // No session yet means Supabase requires confirming the email first —
      // the username (already sent as signup metadata) gets attached to the
      // account once a real session exists (see app/auth/callback/page.tsx).
      if (needsEmailConfirmation || !session) {
        setCheckEmail(true);
        return;
      }
      await applySession(session);
      try {
        await claimUsername(normalizedUsername);
      } catch (err) {
        const message = err instanceof Error ? err.message : '';
        fail(/already taken/i.test(message) ? t('auth.errorUsernameTaken') : message || t('auth.errorUsernameSave'), 'username');
        return;
      }
      router.replace('/');
    } catch (err) {
      fail(err instanceof Error && err.message ? err.message : t('auth.errorSignUp'));
    } finally {
      setBusy(false);
    }
  };

  const oauth = async (provider: OAuthProvider) => {
    setError(null);
    // Inside the desktop app's embedded view, OAuth can't complete on this
    // origin — delegate to the launcher's own native sign-in/sign-up instead.
    const host = desktopHost();
    if (host) { host.signIn(); return; }
    try {
      await signInWithOAuth(provider);
    } catch (err) {
      fail(err instanceof Error && err.message ? err.message : t('auth.errorOAuth'));
    }
  };

  if (checkEmail) {
    return (
      <AuthShell>
        <AuthStatus icon={MailCheck} tone="success" title={t('auth.checkEmailTitle')} body={t('auth.checkEmailBody', { email: email.trim() })}>
          <p className="text-xs text-muted-foreground">{t('auth.checkEmailHint')}</p>
          <Button asChild size="tap" className="h-12"><Link href="/sign-in">{t('auth.backToSignIn')}</Link></Button>
          <Button type="button" size="tap" variant="ghost" onClick={() => setCheckEmail(false)}>{t('auth.useDifferentEmail')}</Button>
        </AuthStatus>
      </AuthShell>
    );
  }

  if (idToken) {
    return (
      <div role="status" className="flex min-h-svh items-center justify-center gap-2 bg-background p-8 text-sm text-muted-foreground">
        <Loader2 aria-hidden className="size-4 animate-spin" />{t('auth.opening')}
      </div>
    );
  }

  const fieldError = (which: FieldError) => (field === which ? error : null);
  return (
    <AuthShell title={t('auth.signUpTitle')} subtitle={t('auth.signUpSubtitle')}
      footer={<>{t('auth.haveAccount')}{' '}<Link href="/sign-in" className="font-semibold text-brand-ink underline-offset-4 hover:underline">{t('auth.signIn')}</Link></>}>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <AuthField label={t('auth.username')} hint={t('auth.usernameHint')} error={fieldError('username')}>
          {(props) => <Input {...props} className={authInputClass} autoComplete="username" autoCapitalize="none" spellCheck={false}
            autoFocus required value={username} onChange={(e) => setUsername(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.email')}>
          {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.password')} hint={t('auth.passwordHint')} error={fieldError('password')}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.confirmPassword')} error={fieldError('confirm')}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" required value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        {error && !field && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.signingUp')}
          disabled={!username.trim() || !email.trim() || !password || !confirmPassword}>{t('auth.signUp')}</SubmitButton>
      </form>
      <OAuthButtons onSelect={(provider) => void oauth(provider)} disabled={busy} />
    </AuthShell>
  );
}
