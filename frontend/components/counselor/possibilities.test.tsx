// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PossibilityCard } from './possibilities';
import { workspaceApi } from '@/lib/api';
import { I18nProvider } from '@/lib/i18n';
import type { Possibility } from '@/lib/possibilities';
vi.mock('@/lib/api', () => ({ workspaceApi: { changePossibility: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const value: Possibility = { id: 'candidate', title: 'Practical work', why: 'Your own project', status: 'suggested', evidence: [], unknowns: [], roadmap_id: null };
it('offers translated student controls and calls the existing workspace API', async () => {
  const changed = vi.fn();
  vi.mocked(workspaceApi.changePossibility).mockResolvedValue({ ...value, status: 'exploring' });
  render(<I18nProvider><PossibilityCard value={value} onChange={changed} /></I18nProvider>);
  expect(screen.getByText('Save for later')).toBeTruthy();
  expect(screen.getByText('Not for me')).toBeTruthy();
  fireEvent.click(screen.getByText('Explore it'));
  await waitFor(() => expect(changed).toHaveBeenCalled());
  expect(workspaceApi.changePossibility).toHaveBeenCalledWith('candidate', 'explore');
});
it('exploring has only dismiss, and chosen has no actions', () => {
  const view = render(<I18nProvider><PossibilityCard value={{ ...value, status: 'exploring' }} onChange={vi.fn()} /></I18nProvider>);
  expect(screen.queryByText('Explore it')).toBeNull();
  expect(screen.queryByText('Save for later')).toBeNull();
  expect(screen.getByText('Not for me')).toBeTruthy();
  view.rerender(<I18nProvider><PossibilityCard value={{ ...value, status: 'chosen' }} onChange={vi.fn()} /></I18nProvider>);
  expect(screen.queryByRole('button')).toBeNull();
});
