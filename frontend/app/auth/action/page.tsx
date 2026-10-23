'use client';

/** Where our account emails land: /auth/action?mode=verifyEmail|resetPassword&oobCode=…
 *
 * verifyEmail applies the code and, if this browser is signed in, refreshes the
 * token and opens the app. resetPassword checks the code first, then asks for
 * the new password. A used or expired code says so and offers a new link. */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CheckCircle2, KeyRound, Link as LinkIcon, Loader2 } from 'lucide-react';
import {
  AuthAlert, AuthField, AuthShell, AuthStatus, FooterLink, InkLink, PasswordInput, SubmitButton,
} from '@/components/auth/auth-shell';
import {
  checkPasswordResetCode, completeEmailVerification, completePasswordReset, signedInUser,
} from '@/lib/auth/service';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { registrationPasswordError } from '@/lib/password-policy';
import { useT } from '@/lib/i18n';

type State =
  | { kind: 'checking' }
  | { kind: 'verified' }
  | { kind: 'reset'; code: string }
  | { kind: 'reset-done' }
  | { kind: 'invalid'; mode: string; message: string };

export default function AuthActionPage() {
  const router = useRouter();
  const t = useT();
  const { applySession } = usePaiAuth();
  const [state, setState] = useState<State>({ kind: 'checking' });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get('mode') || '';
    const code = params.get('oobCode') || '';
    const invalid = (error?: unknown) => setState({
      kind: 'invalid', mode,
      message: error instanceof Error && error.message ? error.message : t('auth.linkInvalidBody'),
    });
    if (!code) { invalid(); return; }
    if (mode === 'verifyEmail') {
      completeEmailVerification(code).then(async (signedInAndVerified) => {
        if (signedInAndVerified) {
          await applySession();
          router.replace('/');
        } else {
          setState({ kind: 'verified' });
        }
      }).catch(invalid);
    } else if (mode === 'resetPassword') {
      checkPasswordResetCode(code).then(() => setState({ kind: 'reset', code })).catch(invalid);
    } else {
      invalid();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- read the link once

  if (state.kind === 'checking') {
    return (
      <div role="status" className="flex min-h-svh items-center justify-center gap-2 bg-auth-page p-8 text-sm text-auth-muted">
        <Loader2 aria-hidden className="size-4 animate-spin" />{t('auth.opening')}
      </div>
    );
  }
  if (state.kind === 'invalid') {
    // A new verification link comes from the signed-in "check your email" screen.
    const newLink = state.mode === 'verifyEmail'
      ? (signedInUser() ? '/auth/verify-email' : '/sign-in')
      : '/forgot-password';
    return (
      <AuthShell footer={<FooterLink href="/sign-in">{t('auth.backToSignIn')}</FooterLink>}>
        <AuthStatus icon={LinkIcon} tone="warning" title={t('auth.linkInvalidTitle')} body={state.message}>
          <InkLink href={newLink}>{t('auth.requestNewLink')}</InkLink>
        </AuthStatus>
      </AuthShell>
    );
  }
  if (state.kind === 'verified') {
    return (
      <AuthShell>
        <AuthStatus icon={CheckCircle2} tone="success" title={t('auth.verifiedTitle')} body={t('auth.verifiedBody')}>
          <InkLink href="/sign-in">{t('auth.signIn')}</InkLink>
        </AuthStatus>
      </AuthShell>
    );
  }
  if (state.kind === 'reset-done') {
    return (
      <AuthShell>
        <AuthStatus icon={KeyRound} tone="success" title={t('auth.resetDoneTitle')} body={t('auth.resetDoneBody')}>
          <InkLink href="/sign-in">{t('auth.signIn')}</InkLink>
        </AuthStatus>
      </AuthShell>
    );
  }
  return <ResetForm code={state.code} onDone={() => setState({ kind: 'reset-done' })} />;
}

function ResetForm({ code, onDone }: { code: string; onDone: () => void }) {
  const t = useT();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [field, setField] = useState<'password' | 'confirm' | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setField(null);
    if (password !== confirm) { setError(t('auth.errorMismatch')); setField('confirm'); return; }
    if (registrationPasswordError(password)) { setError(t('auth.errorWeakPassword')); setField('password'); return; }
    setBusy(true);
    setError('');
    try {
      await completePasswordReset(code, password);
      onDone();
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('auth.errorResetLink'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthShell title={t('auth.resetTitle')} footer={<FooterLink href="/sign-in">{t('auth.backToSignIn')}</FooterLink>}>
      <p className="-mt-5 mb-7 text-center text-sm text-auth-muted">{t('auth.resetSubtitle')}</p>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <AuthField label={t('auth.newPassword')} hint={t('auth.passwordHint')} error={field === 'password' ? error : null}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" placeholder="•••••••" required autoFocus value={password}
            onChange={(event) => setPassword(event.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.confirmPassword')} error={field === 'confirm' ? error : null}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" placeholder="•••••••" required value={confirm}
            onChange={(event) => setConfirm(event.target.value)} disabled={busy} />}
        </AuthField>
        {error && !field && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.updating')}>{t('auth.updatePassword')}</SubmitButton>
      </form>
    </AuthShell>
  );
}
