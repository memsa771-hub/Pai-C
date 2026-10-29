// @vitest-environment jsdom
import { it, expect, vi, beforeEach } from 'vitest';
import { workspaceApi } from '@/lib/api';
import { journeyProgress, signalMet, useJourney, type JourneySignals } from './use-journey';
import { chosenRoute, picture, roadmapPage } from '@/tests/fixtures/counselor';
import copy from './copy.json';

const at = (stage: string | null, moments: Record<string, string>, extra: Partial<JourneySignals> = {}) => journeyProgress({
  picture: { ...picture, stage, moments, picture: notReady },
  possibilities: [], placesSearched: false, roadmap: null, ...extra,
} as JourneySignals);

// The live audit: after six messages the Counselor had *planned* a first
// picture and a follow-up, and the view jumped from B to E with no first
// picture shown and no Mirror ready.
const planned = { explore_area: 'e1', first_picture: 'e2', follow_thread: 'e3' };
const notReady = { ...picture.picture!, ready: false };
const ready = (stage: string | null) => ({ picture: { ...picture, stage, moments: planned } }) as Partial<JourneySignals>;

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
  expect(at('PROPOSED', planned, ready('PROPOSED')).stage.id).toBe('F');
  expect(at(null, planned).stage.id).toBe('E');
});

it('stage E is Your Mirror, reached when the Mirror is ready; at MIRROR the view may show F', () => {
  const stageE = copy.stages.find((s) => s.id === 'E')!;
  expect([stageE.title, stageE.view, stageE.signal]).toEqual(['Your Mirror', 'mirror', 'mirror_ready']);
  const data = (ready: boolean) => ({ picture: { ...picture, picture: { ...picture.picture!, ready } }, possibilities: [], placesSearched: false, roadmap: null }) as JourneySignals;
  expect(signalMet('mirror_ready', data(true))).toBe(true);
  expect(signalMet('mirror_ready', data(false))).toBe(false);
  expect(signalMet('mirror_ready', { ...data(true), picture: { ...picture, picture: null } })).toBe(false);
  expect(signalMet('mirror_confirmed', data(true))).toBe(false); // the old signal is gone
  expect(at('MIRROR', planned).stage.id).toBe('E');
  expect(at('MIRROR', planned, ready('MIRROR')).stage.id).toBe('F');
});

it('reads the Roadmap page: chosen when a route is chosen, J when a step is ticked', () => {
  const data = (roadmap: JourneySignals['roadmap']) => ({ picture, possibilities: [], placesSearched: false, roadmap }) as JourneySignals;
  expect(signalMet('route_checked', data(roadmapPage))).toBe(false); // no such signal: cards alone reach nothing
  expect(signalMet('route_chosen', data(roadmapPage))).toBe(false);
  expect(signalMet('route_chosen', data({ ...roadmapPage, chosen: chosenRoute }))).toBe(true);
  expect(signalMet('route_step_done', data({ ...roadmapPage, chosen: chosenRoute }))).toBe(false);
  expect(signalMet('route_step_done', data({ ...roadmapPage, chosen: { ...chosenRoute, steps_done: ['apply'] } }))).toBe(true);
});

it('stays on G when paths are found and none is explored, even with roadmap cards', () => {
  const found = { possibilities: [{ id: 'p', title: 'Electronics', why: '', status: 'suggested' }], roadmap: roadmapPage } as unknown as Partial<JourneySignals>;
  expect(at(null, planned, found).stage.id).toBe('G');
  const stageH = copy.stages.find((s) => s.id === 'H')!;
  expect([stageH.title, stageH.view, stageH.signal]).toEqual(['Where to study', 'paths', 'places_searched']);
});

it('H is reached by a finished places search on any path, with no old roadmap API', () => {
  const explored = { possibilities: [{ id: 'p', title: 'Electronics', why: '', status: 'exploring' }] } as unknown as Partial<JourneySignals>;
  const confirmed = ready('PROPOSED');
  expect(at(null, planned, { ...confirmed, ...explored }).stage.id).toBe('H');
  expect(at(null, planned, { ...confirmed, ...explored, placesSearched: true }).stage.id).toBe('I');
  expect(signalMet('places_searched', { picture, possibilities: [], placesSearched: true, roadmap: null })).toBe(true);
});

vi.mock('@/lib/api', () => ({ workspaceApi: {
  getCounselorWorkspace: vi.fn(), getPossibilities: vi.fn(), getRoadmapPage: vi.fn(), getPrograms: vi.fn(),
} }));

beforeEach(() => { vi.clearAllMocks(); });

it('reads places search state only for explored paths', async () => {
  const { renderHook, waitFor } = await import('@testing-library/react');
  vi.mocked(workspaceApi.getCounselorWorkspace).mockResolvedValue(picture);
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue([
    { id: 'seen', title: 'A', why: '', status: 'exploring', evidence: [], unknowns: [] },
    { id: 'new', title: 'B', why: '', status: 'suggested', evidence: [], unknowns: [] },
  ]);
  vi.mocked(workspaceApi.getRoadmapPage).mockResolvedValue(roadmapPage);
  vi.mocked(workspaceApi.getPrograms).mockResolvedValue({ status: 'completed', programs: [], missing: [] });
  const { result } = renderHook(() => useJourney());
  await waitFor(() => expect(result.current.data?.placesSearched).toBe(true));
  expect(workspaceApi.getPrograms).toHaveBeenCalledExactlyOnceWith('seen');
});
