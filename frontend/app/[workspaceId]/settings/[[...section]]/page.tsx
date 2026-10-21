'use client';

import { use, useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** Settings live in one place: the workspace's own Settings view. The old
 * /settings pages (and any bookmark into them) land there. */
export default function SettingsRedirect({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = use(params);
  const router = useRouter();

  useEffect(() => {
    router.replace(`/${workspaceId}?view=settings`);
  }, [router, workspaceId]);

  return null;
}
