'use client';

import Link from 'next/link';
import copy from '@/components/counselor/workspace/copy.json';
import { useMyPlan } from '@/components/os/my-plan-context';

/** A direct link to an OS page the student's route does not have: one line and the way on, nothing else (D-z11). */
export function NotInPlan({ workspaceId }: { workspaceId: string }) {
  const { plan } = useMyPlan();
  const first = plan?.pages?.[0];
  const href = first ? `/${workspaceId}/os-${first.key}` : `/${workspaceId}?view=journey`;
  return (
    <div className="mx-auto w-full max-w-3xl">
      <h1 className="text-xl font-bold">{copy.connect.myPlan.notInPlanTitle}</h1>
      <p className="mt-2 text-sm">{copy.connect.myPlan.notInPlan}</p>
      <Link href={href} className="mt-2 inline-block text-sm font-semibold text-primary hover:underline">
        {first ? copy.connect.myPlan.notInPlanLink : copy.connect.myPlan.emptyLink}
      </Link>
    </div>
  );
}
