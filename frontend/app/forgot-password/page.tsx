'use client';

import { useState } from 'react';
import { Send } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { AuthField, AuthShell, AuthStatus, FooterLink, InkLink, SubmitButton, authInputClass, isEmail } from '@/components/auth/auth-shell';
import { requestPasswordReset } from '@/lib/auth/service';
import { useT } from '@/lib/i18n';

export default function ForgotPasswordPage() {
  const t = useT();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!isEmail(email)) { setError(t('auth.errorEmail')); return; }
    setBusy(true);
    try {
      await requestPasswordReset(email.trim());
      setSent(true);
    } catch {
      setError(t('auth.errorRecovery'));
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <AuthShell>
        <AuthStatus icon={Send} tone="success" title={t('auth.resetSentTitle')} body={t('auth.resetSentBody', { email: email.trim() })}>
          <InkLink href="/sign-in">{t('auth.backToSignIn')}</InkLink>
        </AuthStatus>
      </AuthShell>
    );
  }
  return (
    <AuthShell title={t('auth.forgotTitle')} footer={<FooterLink href="/sign-in">{t('auth.backToSignIn')}</FooterLink>}>
      <p className="-mt-5 mb-7 text-center text-sm text-auth-muted">{t('auth.forgotSubtitle')}</p>
      <form onSubmit={submit} className="grid gap-4" noValidate>
        <AuthField label={t('auth.email')} error={error || null}>
          {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" required autoFocus
            placeholder={t('auth.emailPlaceholder')} value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />}
        </AuthField>
        <SubmitButton busy={busy} busyLabel={t('auth.sending')}>{t('auth.sendReset')}</SubmitButton>
      </form>
    </AuthShell>
  );
}
