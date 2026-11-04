// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PathsFound, PossibilityCard } from './possibilities';
import { workspaceApi } from '@/lib/api';
import { I18nProvider } from '@/lib/i18n';
import type { Possibility } from '@/lib/possibilities';
vi.mock('@/lib/api', () => ({ workspaceApi: { changePossibility: vi.fn(), getPossibilities: vi.fn(), getCurrentPaths: vi.fn() } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const value: Possibility = { id: 'candidate', title: 'Practical work', why: 'Your own project', status: 'suggested', evidence: [], unknowns: [] };
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

it('shows the paths PAI found in chat and opens them in the workspace', async () => {
  const fit = [{ label: 'Hands-on work', status: 'have' as const, note: '', evidence: ['I fix phones'] }];
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue([
    { ...value, id: 'a', title: 'Mobile repair', fit, study_field: { key: 'x', needs_check: true, needs_group: [] } },
    { ...value, id: 'b', title: 'Dismissed one', status: 'dismissed' },
    { ...value, id: 'c', title: 'Not in this message' },
  ]);
  window.history.replaceState({}, '', '/my-space?view=threads');
  const moved = vi.fn();
  window.addEventListener('popstate', moved);
  render(<PathsFound ids={['a', 'b']} />);
  expect(await screen.findByText('Mobile repair')).toBeTruthy();
  expect(screen.getByText('Needs checking for your group')).toBeTruthy();
  expect(screen.queryByText('Dismissed one')).toBeNull();
  expect(screen.queryByText('Not in this message')).toBeNull();
  expect(screen.getByText('One path, checked against what you shared.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Open your paths' }));
  expect(window.location.pathname + window.location.search).toBe('/my-space?view=paths');
  expect(moved).toHaveBeenCalledOnce();
  window.removeEventListener('popstate', moved);
});

// req: R-47
const five: Possibility[] = ['a', 'b', 'c', 'd', 'e'].map(id => ({ ...value, id, title: `Path ${id}` }));
const snap = (id: string) => ({ id, title: `Path ${id}`, why: '', fit: undefined, study_field: null });
it('the newest paths card shows the current paths, as Roadmaps does', async () => {
  vi.mocked(workspaceApi.getCurrentPaths).mockResolvedValue(five);
  render(<I18nProvider><PathsFound newest ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>);
  for (const id of ['a', 'b', 'c', 'd', 'e']) await screen.findByText(`Path ${id}`);
  expect(screen.queryByText(/Your paths have changed/)).toBeNull();
});
it('an older paths card keeps its snapshot and does not read the current list', async () => {
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(five);
  render(<I18nProvider><PathsFound ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>);
  await screen.findByText('Path a');
  expect(screen.getByText('Path b')).toBeTruthy();
  expect(screen.queryByText('Path c')).toBeNull();
  expect(workspaceApi.getCurrentPaths).not.toHaveBeenCalled();
});
it('the newest paths card shows its snapshot while the current paths are loading', async () => {
  vi.mocked(workspaceApi.getCurrentPaths).mockReturnValue(new Promise(() => {}));
  render(<I18nProvider><PathsFound newest ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>);
  await screen.findByText('Path a');
  expect(screen.getByText('Path b')).toBeTruthy();
});
it('the newest paths card keeps its snapshot when the current paths cannot be loaded', async () => {
  vi.mocked(workspaceApi.getCurrentPaths).mockRejectedValue(new Error('offline'));
  render(<I18nProvider><PathsFound newest ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>);
  await waitFor(() => expect(workspaceApi.getCurrentPaths).toHaveBeenCalled());
  await act(async () => {});
  await screen.findByText('Path a');
  expect(screen.getByText('Path b')).toBeTruthy();
});
it('a card that becomes the newest drops the list it loaded as an older card', async () => {
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(five);
  vi.mocked(workspaceApi.getCurrentPaths).mockReturnValue(new Promise(() => {}));
  const card = (newest: boolean) => <I18nProvider><PathsFound newest={newest} ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>;
  const view = render(card(false));
  await waitFor(() => expect(workspaceApi.getPossibilities).toHaveBeenCalled());
  await act(async () => {});
  view.rerender(card(true));
  await act(async () => {});
  expect(screen.getByText('Path a')).toBeTruthy();
  expect(screen.queryByText('Path c')).toBeNull();
});
it('the newest paths card drops a removed path when a paths-excluded notice arrives; an unrelated message changes nothing', async () => {
  vi.mocked(workspaceApi.getCurrentPaths).mockResolvedValue(five.slice(0, 2));
  const card = (key?: string) => <I18nProvider><PathsFound newest refreshKey={key} ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>;
  const view = render(card(undefined));
  await screen.findByText('Path b');
  expect(workspaceApi.getCurrentPaths).toHaveBeenCalledTimes(1);
  vi.mocked(workspaceApi.getCurrentPaths).mockResolvedValue([five[0]]);
  view.rerender(card('notice-1'));
  await waitFor(() => expect(screen.queryByText('Path b')).toBeNull());
  expect(screen.getByText('Path a')).toBeTruthy();
  expect(workspaceApi.getCurrentPaths).toHaveBeenCalledTimes(2);
  view.rerender(card('notice-1')); // an unrelated message leaves the key as it was
  await act(async () => {});
  expect(workspaceApi.getCurrentPaths).toHaveBeenCalledTimes(2);
  expect(screen.getByText('Path a')).toBeTruthy();
});
it('an older paths card ignores the refresh key', async () => {
  vi.mocked(workspaceApi.getPossibilities).mockResolvedValue(five);
  const card = (key: string) => <I18nProvider><PathsFound refreshKey={key} ids={['a', 'b']} snapshot={[snap('a'), snap('b')]} /></I18nProvider>;
  const view = render(card('x'));
  await screen.findByText('Path a');
  view.rerender(card('y'));
  await act(async () => {});
  expect(workspaceApi.getPossibilities).toHaveBeenCalledTimes(1);
  expect(workspaceApi.getCurrentPaths).not.toHaveBeenCalled();
});
