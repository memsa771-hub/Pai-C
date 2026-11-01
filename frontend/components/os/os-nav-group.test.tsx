// @vitest-environment jsdom

// Merge pai-c + pai-os: was pai-os's components/layout/nav-main.test.tsx. pai-c deleted nav-main.tsx (the
// old phone drawer); the "Study abroad plan" group now sits in CounselorShell's rail, so this tests
// OsNavGroup itself with the same expectations.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { SidebarProvider } from '@/components/ui/sidebar';
import { I18nProvider } from '@/lib/i18n';
import { OsNavGroup } from './os-nav-group';

const config = vi.hoisted(() => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false }));
vi.mock('@/lib/config', () => ({
  get OS_UI_ENABLED() { return config.OS_UI_ENABLED; },
  get OS_REHEARSAL_UI() { return config.OS_REHEARSAL_UI; },
  OS_FROM_STAGE: 'H',
}));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }) }));

beforeAll(() => {
  window.matchMedia ??= ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => { cleanup(); config.OS_UI_ENABLED = true; config.OS_REHEARSAL_UI = false; });

const view = (onNavigate?: () => void, stageId = 'H', current: 'os-inbox' | null = null) => render(
  <I18nProvider><SidebarProvider><OsNavGroup onNavigate={onNavigate} stageId={stageId} current={current} /></SidebarProvider></I18nProvider>,
);

describe('OsNavGroup study abroad group', () => {
  it('shows the study abroad group when OS is enabled', () => {
    view();
    expect(screen.getByText('Study abroad plan')).toBeTruthy();
    const links = ['Start', 'Inbox', 'Documents', 'Programmes', 'Statements', 'Pack', 'Visa']
      .map((name) => [name, screen.getByRole('link', { name }).getAttribute('href')]);
    expect(links).toEqual([
      ['Start', '/ws1/os-start'], ['Inbox', '/ws1/os-inbox'], ['Documents', '/ws1/os-documents'],
      ['Programmes', '/ws1/os-programmes'], ['Statements', '/ws1/os-statements'], ['Pack', '/ws1/os-pack'],
      ['Visa', '/ws1/os-visa'],
    ]);
  });

  it('calls onNavigate when a link is chosen', () => {
    const onNavigate = vi.fn();
    view(onNavigate);
    fireEvent.click(screen.getByRole('link', { name: 'Inbox' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it('hides it when OS is disabled', () => {
    config.OS_UI_ENABLED = false;
    view();
    expect(screen.queryByText('Study abroad plan')).toBeNull();
    expect(screen.queryByRole('link', { name: 'Start' })).toBeNull();
  });
});

describe('when the study abroad plan opens', () => {
  it('opens from stage H, not before (paths first, places later)', () => {
    view(undefined, 'B');
    expect(screen.queryByText('Study abroad plan')).toBeNull();
    cleanup();
    view(undefined, 'J');
    expect(screen.getByText('Study abroad plan')).toBeTruthy();
  });

  it('opens at any stage in a rehearsal', () => {
    config.OS_REHEARSAL_UI = true;
    view(undefined, 'B');
    expect(screen.getByText('Study abroad plan')).toBeTruthy();
  });

  it('marks the page shown now', () => {
    view(undefined, 'H', 'os-inbox');
    expect(screen.getByRole('link', { name: 'Inbox' }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByRole('link', { name: 'Start' }).getAttribute('aria-current')).toBeNull();
  });
});
