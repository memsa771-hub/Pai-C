'use client';

/** "Check your email" after an email sign-up, or when an unverified account
 * signs in: resend the link (with a cooldown), continue once verified, or
 * start again with a different email. */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ActionButton, AuthAlert, AuthStatus } from '@/components/auth/auth-shell';
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
    <>
      <AuthStatus title={t('auth.checkEmailTitle')} body={t('auth.checkEmailBody', { email })}>
        {note && (note.kind === 'error'
          ? <AuthAlert>{note.text}</AuthAlert>
          : <p className="text-sm font-medium text-success-ink">{note.text}</p>)}
        <ActionButton busy={busy} onClick={() => void finish()}>{t('auth.checkedEmail')}</ActionButton>
        <p className="text-[13px] leading-[1.45] text-auth-muted">
          {t('auth.checkEmailHint')}{' '}
          <button type="button" disabled={busy || wait > 0} onClick={() => void resend()}
            className="-my-3 py-3 font-bold text-auth-blue hover:underline disabled:font-medium disabled:text-auth-muted disabled:no-underline">
            {wait > 0 ? t('auth.resendIn', { seconds: wait }) : t('auth.resend')}
          </button>
        </p>
      </AuthStatus>
      <div className="mt-[var(--auth-gap)] flex flex-wrap justify-center gap-[5px] text-[13px] leading-[1.45]">
        <span>{t('auth.wrongEmail')}</span>
        <button type="button" onClick={() => void differentEmail()} className="-my-3 py-3 font-bold text-auth-blue hover:underline">
          {t('auth.useDifferentEmail')}
        </button>
      </div>
    </>
  );
}
