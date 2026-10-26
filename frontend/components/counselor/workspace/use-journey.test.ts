import { it, expect } from 'vitest';
import { journeyProgress, signalMet, type JourneySignals } from './use-journey';
import { chosenRoute, picture, roadmapPage } from '@/tests/fixtures/counselor';

const at = (stage: string | null, moments: Record<string, string>, extra: Partial<JourneySignals> = {}) => journeyProgress({
  picture: { ...picture, stage, moments, mirror_status: null },
  possibilities: [], roadmap: null, ...extra,
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

it('reads the Roadmap page: checked when cards exist, chosen when a route is chosen', () => {
  const data = (roadmap: JourneySignals['roadmap']) => ({ picture, possibilities: [], roadmap }) as JourneySignals;
  expect(signalMet('route_checked', data(null))).toBe(false);
  expect(signalMet('route_checked', data({ ...roadmapPage, fields: [] }))).toBe(false);
  expect(signalMet('route_checked', data(roadmapPage))).toBe(true);
  expect(signalMet('route_chosen', data(roadmapPage))).toBe(false);
  expect(signalMet('route_chosen', data({ ...roadmapPage, chosen: chosenRoute }))).toBe(true);
  expect(signalMet('route_step_done', data({ ...roadmapPage, chosen: { ...chosenRoute, steps_done: [false, false, false] } }))).toBe(false);
  expect(signalMet('route_step_done', data({ ...roadmapPage, chosen: chosenRoute }))).toBe(true);
});
