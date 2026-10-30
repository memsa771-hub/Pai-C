// @vitest-environment jsdom

// Merge pai-c + pai-os: was pai-os's components/layout/nav-main.test.tsx. pai-c deleted nav-main.tsx (the
// old phone drawer); the "Study abroad plan" group now sits in CounselorShell's rail, so this tests
// OsNavGroup itself with the same expectations.
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { SidebarProvider } from '@/components/ui/sidebar';
import { I18nProvider } from '@/lib/i18n';
import { OsNavGroup } from './os-nav-group';

const config = vi.hoisted(() => ({ OS_UI_ENABLED: true }));
vi.mock('@/lib/config', () => ({
  get OS_UI_ENABLED() { return config.OS_UI_ENABLED; },
}));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }) }));

beforeAll(() => {
  window.matchMedia ??= ((q: string) => ({
    matches: false, media: q, onchange: null, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});
afterEach(() => { cleanup(); config.OS_UI_ENABLED = true; });

const view = (onNavigate?: () => void) => render(
  <I18nProvider><SidebarProvider><OsNavGroup onNavigate={onNavigate} /></SidebarProvider></I18nProvider>,
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
