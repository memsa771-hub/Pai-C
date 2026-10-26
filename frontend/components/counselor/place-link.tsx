'use client';
import { ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { openWorkspaceView, VIEW_ALIASES } from './workspace-link';
import copy from './workspace/copy.json';

/** The place in the workspace a Counselor reply points to. Only views the
 * workspace knows render (old names resolve as in URLs); anything else is
 * ignored. */
export function PlaceLink({ place: raw }: { place: string }) {
  const place = Object.hasOwn(VIEW_ALIASES, raw) ? VIEW_ALIASES[raw] : raw;
  if (!Object.hasOwn(copy.nav, place)) return null;
  return (
    <Button size="sm" variant="soft" className="mt-2" onClick={() => openWorkspaceView(place)}>
      {copy.nav[place as keyof typeof copy.nav]}<ArrowRight aria-hidden />
    </Button>
  );
}
