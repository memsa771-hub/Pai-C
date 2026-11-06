'use client';

import { use, useEffect, useState } from 'react';
import { notFound } from 'next/navigation';
import { OsHeader } from '@/components/os/os-header';
import { useMyPlan } from '@/components/os/my-plan-context';
import { NotInPlan } from '@/components/os/not-in-plan';
import { inPlan, pageNoun, pageTitle } from '@/lib/os-my-plan';
import { ProgrammeFacts } from '@/components/os/programme-facts';
import { workspaceApi } from '@/lib/api';
import { OS_UI_ENABLED } from '@/lib/config';
import type { OsProgramme } from '@/lib/os-programmes';
import { usePaiAuth } from '@/lib/pai-auth-context';
import { goToSignIn } from '@/lib/auth-redirects';

/** PAI OS programme facts: /<workspace>/os-programmes. Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsProgrammesPage({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = use(params);
  const { on, plan } = useMyPlan();  // P1-T9: the route's own page words; off, today's
  const { user, idToken, loading } = usePaiAuth();
  const [programmes, setProgrammes] = useState<OsProgramme[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!OS_UI_ENABLED || loading) return;
    if (!user) {
      goToSignIn();
      return;
    }
    // Placement AI: the bearer alone authorizes the call (no workspace token in the browser).
    workspaceApi.configure(workspaceId, '', idToken || undefined);
    workspaceApi.getOsProgrammes().then(
      (p) => { setProgrammes(p); setError(null); },
      () => setError('Could not load your programmes. Please try again.'),
    );
  }, [loading, user, idToken, workspaceId]);

  if (!OS_UI_ENABLED) notFound();

  if (on && !inPlan(plan, 'programmes')) return <NotInPlan workspaceId={workspaceId} />;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <OsHeader workspaceId={workspaceId} current="os-programmes" title={pageTitle(plan, 'programmes', 'Your programmes')} />
      {error && <p role="alert" className="mb-3 text-sm text-destructive">{error}</p>}
      {programmes === null ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <ProgrammeFacts programmes={programmes} />
      )}
    </div>
  );
}
