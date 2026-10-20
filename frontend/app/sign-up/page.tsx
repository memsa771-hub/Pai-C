'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, MailCheck } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, AuthStatus, FooterLink, GoogleButton, InkLink, PasswordInput, SubmitButton, authInputClass, isEmail } from '@/components/auth/auth-shell';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { signUpWithPassword, signInWithOAuth } from '@/lib/auth/service';
import { registrationPasswordError } from '@/lib/password-policy';
import { desktopHost } from '@/lib/desktop-host';
import { useT } from '@/lib/i18n';

type FieldError = 'email' | 'password' | 'confirm' | null;

export default function SignUpPage() {
  const router = useRouter();
  const t = useT();
  const { applySession, idToken } = usePaiAuth();
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
    setError(null); setField(null);
    if (!isEmail(email)) return fail(t('auth.errorEmail'), 'email');
    if (registrationPasswordError(password)) return fail(t('auth.errorWeakPassword'), 'password');
    if (password !== confirmPassword) return fail(t('auth.errorMismatch'), 'confirm');

    setBusy(true);
    try {
      const { session, needsEmailConfirmation } = await signUpWithPassword(email.trim(), password);
      // No session yet means Supabase requires confirming the email first.
      if (needsEmailConfirmation || !session) {
        setCheckEmail(true);
        return;
      }
      await applySession(session);
      router.replace('/');
    } catch (err) {
      fail(err instanceof Error && err.message ? err.message : t('auth.errorSignUp'));
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setError(null);
    // Inside the desktop app's embedded view, OAuth can't complete on this
    // origin — delegate to the launcher's own native sign-in/sign-up instead.
    const host = desktopHost();
    if (host) { host.signIn(); return; }
    try {
      await signInWithOAuth('google');
    } catch (err) {
      fail(err instanceof Error && err.message ? err.message : t('auth.errorOAuth'));
    }
  };

  if (checkEmail) {
    return (
      <AuthShell>
        <AuthStatus icon={MailCheck} tone="success" title={t('auth.checkEmailTitle')} body={t('auth.checkEmailBody', { email: email.trim() })}>
          <p className="text-xs text-auth-muted">{t('auth.checkEmailHint')}</p>
          <InkLink href="/sign-in">{t('auth.backToSignIn')}</InkLink>
          <button type="button" onClick={() => setCheckEmail(false)}
            className="min-h-11 text-sm font-medium text-auth-ink underline-offset-4 hover:underline">
            {t('auth.useDifferentEmail')}
          </button>
        </AuthStatus>
      </AuthShell>
    );
  }

  if (idToken) {
    return (
      <div role="status" className="flex min-h-svh items-center justify-center gap-2 bg-auth-page p-8 text-sm text-auth-muted">
        <Loader2 aria-hidden className="size-4 animate-spin" />{t('auth.opening')}
      </div>
    );
  }

  const fieldError = (which: FieldError) => (field === which ? error : null);
  return (
    <AuthShell title={t('auth.signUpTitle')}
      footer={<>{t('auth.haveAccount')}{' '}<FooterLink href="/sign-in">{t('auth.signIn')}</FooterLink></>}>
      <GoogleButton label={t('auth.googleSignUp')} onClick={() => void google()} disabled={busy} />
      <form onSubmit={submit} className="mt-6 grid gap-4" noValidate>
        <AuthField label={t('auth.email')} error={fieldError('email')}>
          {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" autoCapitalize="none"
            spellCheck={false} placeholder={t('auth.emailPlaceholder')} required value={email}
            onChange={(e) => setEmail(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.password')} hint={t('auth.passwordHint')} error={fieldError('password')}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" placeholder="•••••••" required value={password}
            onChange={(e) => setPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.confirmPassword')} error={fieldError('confirm')}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" placeholder="•••••••" required value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)} disabled={busy} />}
        </AuthField>
        {error && !field && <AuthAlert>{error}</AuthAlert>}
        <div className="pt-1">
          <SubmitButton busy={busy} busyLabel={t('auth.signingUp')}>{t('auth.signUp')}</SubmitButton>
        </div>
      </form>
    </AuthShell>
  );
}
