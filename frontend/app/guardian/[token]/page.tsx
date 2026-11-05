'use client';

import { use, useEffect, useState } from 'react';
import Image from 'next/image';
import { Loader2 } from 'lucide-react';
import { useT } from '@/lib/i18n';
import {
  answerGuardian,
  GuardianError,
  loadGuardianPage,
  type GuardianAnswer,
  type GuardianMode,
  type GuardianPage,
} from '@/lib/guardian';

type View =
  | { kind: 'loading' }
  | { kind: 'ask'; mode: GuardianMode; page: GuardianPage }
  | { kind: 'done'; answer: GuardianAnswer; mode: GuardianMode; confirmationSent: boolean }
  | { kind: 'error'; problem: 'busy' | 'unavailable' | 'network' };

type Key = Parameters<ReturnType<typeof useT>>[0];
const DONE: Record<GuardianAnswer, [Key, Key]> = {
  agreed: ['guardian.agreedTitle', 'guardian.agreedBody'],
  withdrawn: ['guardian.withdrawnTitle', 'guardian.withdrawnBody'],
  expired: ['guardian.expiredTitle', 'guardian.expiredBody'],
  used: ['guardian.usedTitle', 'guardian.usedBody'],
  stale: ['guardian.staleTitle', 'guardian.staleBody'],
};
const STALE_WITHDRAW: [Key, Key] = ['guardian.staleWithdrawTitle', 'guardian.staleWithdrawBody'];
const AGREED_NO_MAIL: [Key, Key] = ['guardian.agreedTitle', 'guardian.agreedNoMailBody'];
const PROBLEM: Record<'busy' | 'unavailable' | 'network', [Key, Key]> = {
  busy: ['guardian.busyTitle', 'guardian.busyBody'],
  unavailable: ['guardian.unavailableTitle', 'guardian.unavailableBody'],
  network: ['guardian.errorTitle', 'guardian.errorBody'],
};

// Public page for a parent or guardian: no sign-in, no student data but the first name, and the token only in the path.
export default function GuardianPageRoute({ params }: { params: Promise<{ token: string }> }) {
  const t = useT();
  const { token } = use(params);
  const [view, setView] = useState<View>({ kind: 'loading' });
  const [sending, setSending] = useState(false);

  useEffect(() => {
    let live = true;
    loadGuardianPage(token).then(
      ({ mode, page }) => {
        if (!live) return;
        setView(page.state === 'ok' ? { kind: 'ask', mode, page }
          : { kind: 'done', answer: page.state, mode, confirmationSent: false });
      },
      (e) => live && setView({ kind: 'error', problem: e instanceof GuardianError ? e.kind : 'network' }),
    );
    return () => {
      live = false;
    };
  }, [token]);

  async function press(mode: GuardianMode) {
    if (sending) return;
    setSending(true);
    try {
      const { state, confirmationSent } = await answerGuardian(token, mode);
      setView({ kind: 'done', answer: state, mode, confirmationSent });
    } catch (e) {
      setView({ kind: 'error', problem: e instanceof GuardianError ? e.kind : 'network' });
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-5 bg-background px-4 py-10">
      <Image src="/pai-emblem.png" alt={t('guardian.brand')} width={40} height={40} />
      <div className="w-full max-w-md space-y-4" aria-live="polite">
        {view.kind === 'loading' && (
          <div className="flex justify-center" role="status" aria-label={t('guardian.loading')}>
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        )}
        {view.kind === 'ask' && <Ask view={view} sending={sending} onPress={press} />}
        {view.kind === 'done' && <Done view={view} />}
        {view.kind === 'error' && <Message title={t(PROBLEM[view.problem][0])} body={t(PROBLEM[view.problem][1])} />}
      </div>
    </main>
  );
}

function Done({ view }: { view: Extract<View, { kind: 'done' }> }) {
  const t = useT();
  // A withdraw link that finds no agreement has its own wording; so has an agreement whose mail did not go out.
  const [title, body] = view.answer === 'stale' && view.mode === 'withdraw' ? STALE_WITHDRAW
    : view.answer === 'agreed' && !view.confirmationSent ? AGREED_NO_MAIL : DONE[view.answer];
  return <Message title={t(title)} body={t(body)} />;
}

function Message({ title, body }: { title: string; body: string }) {
  return (
    <div className="space-y-2 text-center" data-testid="guardian-message">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="text-sm text-muted-foreground">{body}</p>
    </div>
  );
}

function Ask({ view, sending, onPress }: { view: Extract<View, { kind: 'ask' }>; sending: boolean; onPress: (m: GuardianMode) => void }) {
  const t = useT();
  const { mode, page } = view;
  // Both pages show the approved wording the API sends.
  const title = page.text?.title;
  const body = page.text?.body ?? [];
  const button = mode === 'agree' ? page.text?.agree_button : page.text?.withdraw_button;
  return (
    <div className="space-y-4" data-testid={`guardian-${mode}`}>
      <h1 className="text-xl font-semibold">{title}</h1>
      {body.map((p, i) => (
        <p key={i} className="text-sm text-muted-foreground">{p}</p>
      ))}
      <button type="button" disabled={sending} onClick={() => onPress(mode)}
              className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground disabled:opacity-60">
        {sending ? t('guardian.working') : button}
      </button>
    </div>
  );
}
