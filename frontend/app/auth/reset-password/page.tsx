'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, LinkIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AuthAlert, AuthField, AuthShell, AuthStatus, PasswordInput, SubmitButton } from '@/components/auth/auth-shell';
import { completePasswordReset } from '@/lib/auth/service';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { registrationPasswordError } from '@/lib/password-policy';
import { useT } from '@/lib/i18n';

export default function ResetPasswordPage() {
  const router = useRouter();
  const t = useT();
  const { applySession } = usePaiAuth();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [field, setField] = useState<'password' | 'confirm' | null>(null);
  const [linkInvalid, setLinkInvalid] = useState(false);

  // A link without a code (or one the provider rejected) can never succeed,
  // so say so up front instead of after the student types a new password.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (!params.get('code') || params.get('error')) setLinkInvalid(true);
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setField(null);
    if (password !== confirm) { setError(t('auth.errorMismatch')); setField('confirm'); return; }
    if (registrationPasswordError(password)) { setError(t('auth.errorWeakPassword')); setField('password'); return; }
    setBusy(true);
    setError('');
    try {
      const params = new URLSearchParams(window.location.search);
      const code = params.get('code');
      if (!code || params.get('error')) throw new Error(t('auth.errorResetLink'));
      const session = await completePasswordReset(code, password);
      await applySession(session);
      router.replace('/');
    } catch (reason) {
      setError(reason instanceof Error && reason.message ? reason.message : t('auth.errorResetLink'));
    } finally {
      setBusy(false);
    }
  };

  if (linkInvalid) {
    return (
      <AuthShell>
        <AuthStatus icon={LinkIcon} tone="warning" title={t('auth.linkInvalidTitle')} body={t('auth.linkInvalidBody')}>
          <Button asChild size="tap" className="h-12"><Link href="/forgot-password">{t('auth.requestNewLink')}</Link></Button>
          <Button asChild size="tap" variant="ghost"><Link href="/sign-in">{t('auth.backToSignIn')}</Link></Button>
        </AuthStatus>
      </AuthShell>
    );
  }
  return (
    <AuthShell title={t('auth.resetTitle')} subtitle={t('auth.resetSubtitle')}
      footer={<Link href="/sign-in" className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-brand-ink underline-offset-4 hover:underline"><ArrowLeft aria-hidden className="size-4" />{t('auth.backToSignIn')}</Link>}>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <AuthField label={t('auth.newPassword')} hint={t('auth.passwordHint')} error={field === 'password' ? error : null}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" required autoFocus value={password}
            onChange={(event) => setPassword(event.target.value)} disabled={busy} />}
        </AuthField>
        <AuthField label={t('auth.confirmPassword')} error={field === 'confirm' ? error : null}>
          {(props) => <PasswordInput {...props} autoComplete="new-password" required value={confirm}
            onChange={(event) => setConfirm(event.target.value)} disabled={busy} />}
        </AuthField>
        {error && !field && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.updating')} disabled={!password || !confirm}>{t('auth.updatePassword')}</SubmitButton>
      </form>
    </AuthShell>
  );
}
