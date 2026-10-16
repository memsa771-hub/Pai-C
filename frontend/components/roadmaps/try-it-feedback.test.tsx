// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import { RoadmapFit } from './roadmap-fit';
import type { Roadmap } from '@/lib/roadmaps';
vi.mock('@/lib/api', () => ({ workspaceApi: { sendEvent: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const base = { id: 'roadmap', title: 'Practical route', lane: 'discovered', gaps: [],
  test_30_days: 'An older activity',
  try_it: { kind: 'talk_to_someone', what: 'Talk with someone doing the work', time_needed: 'An hour',
    questions: ['What does a typical day involve?', 'What is difficult?', 'What do you enjoy?'] } } as Roadmap;
it('shows Try-it and sends one normal student event with route metadata, without dismissing', async () => {
  vi.mocked(workspaceApi.sendEvent).mockResolvedValue({ id: 'feedback' } as never);
  render(<I18nProvider><RoadmapFit roadmap={base} /></I18nProvider>);
  expect(screen.getByText('Talk with someone doing the work')).toBeTruthy();
  expect(screen.getByText('What do you enjoy?')).toBeTruthy();
  expect(screen.queryByText('An older activity')).toBeNull();
  fireEvent.click(screen.getByText('I tried it'));
  fireEvent.click(screen.getByText('Not for me'));
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'I enjoyed the people but not the routine.' } });
  fireEvent.click(screen.getByText('Send'));
  await waitFor(() => expect(screen.getByText('Shared with PAI')).toBeTruthy());
  expect(workspaceApi.sendEvent).toHaveBeenCalledTimes(1);
  expect(workspaceApi.sendEvent).toHaveBeenCalledWith({ type: 'workspace.message.posted', target: 'channel/pai-counselor',
    payload: { content: 'Practical route, Try it: Not for me. I enjoyed the people but not the routine.', message_type: 'chat' },
    metadata: { target_agents: ['pai'], try_it_roadmap_id: 'roadmap' }, visibility: 'channel' });
});
it('keeps old saved activities readable without a Try-it form', () => {
  render(<I18nProvider><RoadmapFit roadmap={{ ...base, try_it: undefined }} /></I18nProvider>);
  expect(screen.getByText('An older activity')).toBeTruthy();
  expect(screen.queryByText('I tried it')).toBeNull();
});
