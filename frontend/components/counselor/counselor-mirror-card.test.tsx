// @vitest-environment jsdom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CounselorMirrorCard } from './counselor-mirror-card';
import { I18nProvider } from '../../lib/i18n';
import { workspaceApi } from '../../lib/api';
import type { CounselorMirrorDraft } from '../../lib/counselor-mirror';

vi.mock('../../lib/api', () => ({ workspaceApi: {
  getCounselorSummary: vi.fn(), confirmCounselorMirror: vi.fn(), editCounselorMirror: vi.fn(),
} }));

const draft: CounselorMirrorDraft = {
  type: 'mirror', status: 'awaiting_confirmation', version: 3,
  mirror: { intro: 'Here is your picture.', confidence: 'full',
    dimensions: [{ key: 'education', name: 'Your learning', picture: 'You enjoy practical work.',
      evidence: 'You described a completed project.', unknown: false }],
    blockers: ['Time needs clarification.', 'The direction needs testing.'],
    opinion: 'Your actions suggest practical learning matters.', question: 'What should I change?',
    roadmap_lanes: [] },
};

beforeEach(() => {
  vi.mocked(workspaceApi.getCounselorSummary).mockResolvedValue(structuredClone(draft));
  vi.mocked(workspaceApi.confirmCounselorMirror).mockResolvedValue(undefined);
  vi.mocked(workspaceApi.editCounselorMirror).mockResolvedValue(undefined);
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const show = () => render(<I18nProvider><CounselorMirrorCard refreshKey="one" /></I18nProvider>);

it('renders translated controls and expandable picture/evidence without internal lane data', async () => {
  show();
  expect(await screen.findByRole('region', { name: 'Your 360-degree picture' })).toBeTruthy();
  expect(screen.getByText('You described a completed project.', { exact: false })).toBeTruthy();
  const summary = screen.getByText('Your learning');
  expect(summary.closest('details')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Yes, that is right' })).toBeTruthy();
  expect(screen.queryByText('roadmap_lanes')).toBeNull();
  expect(document.body.textContent).not.toContain('counselorMirror.');
});

it('confirms the current version once and replaces buttons with translated status', async () => {
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, that is right' }));
  await waitFor(() => expect(workspaceApi.confirmCounselorMirror).toHaveBeenCalledExactlyOnceWith(3));
  expect(await screen.findByRole('status')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Yes, that is right' })).toBeNull();
});

it('opens Edit and posts the correction through the versioned API', async () => {
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'What should PAI change?' }),
    { target: { value: '  My available time is different.  ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send corrections to PAI' }));
  await waitFor(() => expect(workspaceApi.editCounselorMirror).toHaveBeenCalledExactlyOnceWith(3, 'My available time is different.'));
  expect(workspaceApi.confirmCounselorMirror).not.toHaveBeenCalled();
});

it('keeps the review actionable after an API error and shows a translated error', async () => {
  vi.mocked(workspaceApi.confirmCounselorMirror).mockRejectedValue(new Error('internal details'));
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Yes, that is right' }));
  expect((await screen.findByRole('alert')).textContent).toBe('We could not complete that action. Please try again.');
  expect(document.body.textContent).not.toContain('internal details');
});
