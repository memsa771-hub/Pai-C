'use client';

/** "Check your email" after an email sign-up, or when an unverified account
 * signs in: resend the link (with a cooldown), continue once verified, or
 * start again with a different email. */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { MailCheck } from 'lucide-react';
import { AuthAlert, AuthStatus, InkLink } from '@/components/auth/auth-shell';
import { refreshVerification, sendVerificationEmail, signOut } from '@/lib/auth/service';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { useT } from '@/lib/i18n';

const COOLDOWN_SECONDS = 60;

export function CheckEmailStatus({ email, justSent = true, onDifferentEmail }: {
  email: string;
  /** The first email went out a moment ago, so the cooldown starts now. */
  justSent?: boolean;
  onDifferentEmail?: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const { applySession } = usePaiAuth();
  const [wait, setWait] = useState(justSent ? COOLDOWN_SECONDS : 0);
  const [note, setNote] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!wait) return;
    const timer = setTimeout(() => setWait((left) => left - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const resend = async () => {
    setBusy(true); setNote(null);
    try {
      const result = await sendVerificationEmail();
      if (result.alreadyVerified) { await finish(); return; }
      setNote({ kind: 'ok', text: t('auth.resent') });
      setWait(COOLDOWN_SECONDS);
    } catch (error) {
      setNote({ kind: 'error', text: error instanceof Error ? error.message : t('auth.errorSignUp') });
    } finally {
      setBusy(false);
    }
  };

  const finish = async () => {
    const verified = await refreshVerification();
    if (verified === null) { router.replace('/sign-in'); return; }
    if (!verified) { setNote({ kind: 'error', text: t('auth.stillUnverified') }); return; }
    await applySession();
    router.replace('/');
  };

  const differentEmail = async () => {
    await signOut();
    if (onDifferentEmail) onDifferentEmail();
    else router.replace('/sign-up');
  };

  return (
    <AuthStatus icon={MailCheck} tone="success" title={t('auth.checkEmailTitle')} body={t('auth.checkEmailBody', { email })}>
      <p className="text-xs text-auth-muted">{t('auth.checkEmailHint')}</p>
      {note && (note.kind === 'error'
        ? <AuthAlert>{note.text}</AuthAlert>
        : <p role="status" className="text-sm font-medium text-success-ink">{note.text}</p>)}
      <button type="button" disabled={busy} onClick={() => void finish()}
        className="min-h-11 text-sm font-bold text-auth-blue hover:underline disabled:opacity-60">
        {t('auth.checkedEmail')}
      </button>
      <button type="button" disabled={busy || wait > 0} onClick={() => void resend()}
        className="min-h-11 text-sm font-bold text-auth-blue disabled:font-medium disabled:text-auth-muted">
        {wait > 0 ? t('auth.resendIn', { seconds: wait }) : t('auth.resend')}
      </button>
      <InkLink href="/sign-in">{t('auth.backToSignIn')}</InkLink>
      <button type="button" onClick={() => void differentEmail()}
        className="min-h-11 text-sm font-medium text-auth-ink underline-offset-4 hover:underline">
        {t('auth.useDifferentEmail')}
      </button>
    </AuthStatus>
  );
}
