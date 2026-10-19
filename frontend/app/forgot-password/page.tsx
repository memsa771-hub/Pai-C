'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { AuthAlert, AuthField, AuthShell, AuthStatus, SubmitButton, authInputClass } from '@/components/auth/auth-shell';
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
    setBusy(true);
    setError('');
    try {
      await requestPasswordReset(email.trim());
      setSent(true);
    } catch {
      setError(t('auth.errorRecovery'));
    } finally {
      setBusy(false);
    }
  };

  const back = <Link href="/sign-in" className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-brand-ink underline-offset-4 hover:underline"><ArrowLeft aria-hidden className="size-4" />{t('auth.backToSignIn')}</Link>;
  if (sent) {
    return (
      <AuthShell>
        <AuthStatus icon={Send} tone="success" title={t('auth.resetSentTitle')} body={t('auth.resetSentBody', { email: email.trim() })}>
          <Button asChild size="tap" className="h-12"><Link href="/sign-in">{t('auth.backToSignIn')}</Link></Button>
        </AuthStatus>
      </AuthShell>
    );
  }
  return (
    <AuthShell title={t('auth.forgotTitle')} subtitle={t('auth.forgotSubtitle')} footer={back}>
      <form onSubmit={submit} className="grid gap-4">
        <AuthField label={t('auth.email')}>
          {(props) => <Input {...props} className={authInputClass} type="email" autoComplete="email" required autoFocus
            value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />}
        </AuthField>
        {error && <AuthAlert>{error}</AuthAlert>}
        <SubmitButton busy={busy} busyLabel={t('auth.sending')} disabled={!email.trim()}>{t('auth.sendReset')}</SubmitButton>
      </form>
    </AuthShell>
  );
}
