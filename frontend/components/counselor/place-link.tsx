'use client';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { openWorkspaceView } from './workspace-link';
import copy from './workspace/copy.json';

/** The place in the workspace a Counselor reply points to. Only views the
 * workspace knows render; anything else is ignored. */
export function PlaceLink({ place }: { place: string }) {
  if (!Object.hasOwn(copy.nav, place)) return null;
  return (
    <Button size="sm" variant="soft" className="mt-2" onClick={() => openWorkspaceView(place)}>
      {copy.nav[place as keyof typeof copy.nav]}<ArrowRight aria-hidden />
    </Button>
  );
}
