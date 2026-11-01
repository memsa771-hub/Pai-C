'use client';

import { use, Suspense } from 'react';
import { WorkspaceGate, WorkspaceLoadingSplash } from '@/components/layout/workspace-gate';

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);

  return (
    <Suspense fallback={<WorkspaceLoadingSplash />}>
      <WorkspaceGate workspaceId={workspaceId} />
    </Suspense>
  );
}
