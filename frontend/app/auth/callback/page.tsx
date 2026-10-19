'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Loader2, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AuthShell, AuthStatus } from '@/components/auth/auth-shell';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { completeOAuth } from '@/lib/auth/service';
import { useT } from '@/lib/i18n';

function AuthCallback() {
  const router = useRouter();
  const t = useT();
  const { applySession } = usePaiAuth();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const oauthError = params.get('error_description') || params.get('error');
    if (oauthError) { setError(t('auth.callbackCancelled')); return; }
    if (!code) { setError(t('auth.callbackMissing')); return; }
    if (started.current) return;
    started.current = true;

    void (async () => {
      try {
        const session = await completeOAuth(code);
        await applySession(session);
        router.replace('/');
      } catch (e) {
        setError(e instanceof Error && e.message ? e.message : t('auth.errorSignIn'));
      }
    })();
  }, [applySession, router, t]);

  if (error) {
    return (
      <AuthShell>
        <AuthStatus icon={ShieldAlert} tone="warning" title={t('auth.callbackFailedTitle')} body={error}>
          <Button asChild size="tap" className="h-12"><Link href="/sign-in">{t('auth.backToSignIn')}</Link></Button>
        </AuthStatus>
      </AuthShell>
    );
  }
  return (
    <div role="status" className="fixed inset-0 flex items-center justify-center gap-2 bg-background text-sm text-muted-foreground">
      <Loader2 aria-hidden className="size-5 animate-spin text-brand" />{t('auth.signingInStatus')}
    </div>
  );
}

export default function AuthCallbackPage() {
  return <AuthCallback />;
}
