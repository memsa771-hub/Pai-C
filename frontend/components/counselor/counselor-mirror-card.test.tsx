// @vitest-environment jsdom

import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { CounselorMirrorCard } from './counselor-mirror-card';
import { I18nProvider } from '../../lib/i18n';
import { workspaceApi } from '../../lib/api';
import type { CounselorMirrorDraft } from '../../lib/counselor-mirror';

vi.mock('../../lib/api', () => ({ workspaceApi: { getCounselorSummary: vi.fn() } }));

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
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const show = () => render(<I18nProvider><CounselorMirrorCard refreshKey="one" /></I18nProvider>);

it('renders an old picture read-only, with expandable evidence and no internal lane data', async () => {
  show();
  expect(await screen.findByRole('region', { name: 'Your 360-degree picture' })).toBeTruthy();
  expect(screen.getByText('You described a completed project.', { exact: false })).toBeTruthy();
  const summary = screen.getByText('Your learning');
  expect(summary.closest('details')).toBeTruthy();
  // No confirm, edit or rating: those routes are gone (FOUR_FEATURES_SPEC 2.3).
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.queryByText('roadmap_lanes')).toBeNull();
  expect(document.body.textContent).not.toContain('counselorMirror.');
});

it('renders v2 picture before collapsed details, while old drafts have no placeholder picture', async () => {
  const modern = structuredClone(draft);
  modern.mirror!.core_picture = {
    you_say: {text: 'My stated wish.', evidence: 'Student statement', unknown: false},
    life_shows: {text: 'My completed work.', evidence: 'Student experience', unknown: false},
    pressure: {text: 'We have not explored this yet.', evidence: '', unknown: true},
    you_want: {text: 'My tentative wish.', evidence: 'Student statement', unknown: false},
  };
  vi.mocked(workspaceApi.getCounselorSummary).mockResolvedValue(modern);
  show();
  const first = await screen.findByText('You say');
  const details = screen.getByText('Details').closest('details')!;
  expect(details.open).toBe(false);
  expect(first.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText('We have not explored this yet.')).toBeTruthy();
  cleanup();
  vi.mocked(workspaceApi.getCounselorSummary).mockResolvedValue(draft);
  show();
  await screen.findByText('Your learning');
  expect(screen.queryByText('You say')).toBeNull();
  expect(screen.queryByText('Details')).toBeNull();
});
