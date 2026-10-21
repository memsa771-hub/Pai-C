import { it, expect } from 'vitest';
import { journeyProgress, type JourneySignals } from './use-journey';
import { picture } from '@/tests/fixtures/counselor';

const at = (stage: string | null, moments: Record<string, string>, extra: Partial<JourneySignals> = {}) => journeyProgress({
  picture: { ...picture, stage, moments, mirror_status: null },
  possibilities: [], roadmaps: [], decision: null, ...extra,
} as JourneySignals);

// The live audit: after six messages the Counselor had *planned* a first
// picture and a follow-up, and the view jumped from B to E with no first
// picture shown and no Mirror ready.
const planned = { explore_area: 'e1', first_picture: 'e2', follow_thread: 'e3' };

it('never shows a stage the server has not reached', () => {
  expect(at('FOUNDATION', planned).stage.id).toBe('B');
  expect(at('DIRECTION', planned).stage.id).toBe('D');
  expect(at('MIRROR', planned).stage.id).toBe('E');
});

it('lets early paths exist without skipping the conversation stages', () => {
  const early = { possibilities: [{ id: 'p', title: 'Electronics', why: '', status: 'suggested' }] } as unknown as Partial<JourneySignals>;
  expect(at('DIRECTION', planned, early).stage.id).toBe('D');
});

it('does not cap later stages, and an unknown stage keeps the signal view', () => {
  expect(at('RESEARCHING', { ...planned, mirror: 'e4' }, { picture: { ...picture, stage: 'RESEARCHING', moments: planned, mirror_status: 'confirmed' } } as Partial<JourneySignals>).stage.id).toBe('F');
  expect(at(null, planned).stage.id).toBe('E');
});
