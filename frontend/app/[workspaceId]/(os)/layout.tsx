'use client';

import { use, Suspense } from 'react';
import { notFound } from 'next/navigation';
import { WorkspaceGate, WorkspaceLoadingSplash } from '@/components/layout/workspace-gate';
import { OS_UI_ENABLED } from '@/lib/config';

/** The PAI OS student pages (/<workspace>/os-*) open the workspace the same way the workspace page does (sign-in, the
 * account's own workspace, onboarding) and render inside the counsellor shell: one rail, one header, one tab bar.
 * Hidden unless NEXT_PUBLIC_OS_ENABLED=true. */
export default function OsLayout({ children, params }: {
  children: React.ReactNode;
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  if (!OS_UI_ENABLED) notFound();
  return (
    <Suspense fallback={<WorkspaceLoadingSplash />}>
      <WorkspaceGate workspaceId={workspaceId}>{children}</WorkspaceGate>
    </Suspense>
  );
}
