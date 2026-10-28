// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { OsHeader } from './os-header';
import { I18nProvider } from '@/lib/i18n';

afterEach(() => cleanup());

function header(current: Parameters<typeof OsHeader>[0]['current'] = 'os-inbox') {
  return render(<I18nProvider><OsHeader workspaceId="w1" current={current} title="Your next steps" /></I18nProvider>);
}

// Slice 9 Task 11: `walk:S1:no_menu_on_os_pages`, a phone user can move between the OS pages from the page itself.
describe('OsHeader', () => {
  it('shows the page title and a closed Menu button', () => {
    header();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Your next steps');
    expect(screen.getByRole('button', { name: 'Menu' }).getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('Menu opens links to every OS page and back to the main menu, marking this page', () => {
    header('os-visa');
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    const links = screen.getAllByRole('link');
    expect(links.map((l) => l.getAttribute('href'))).toEqual([
      '/w1/os-start', '/w1/os-inbox', '/w1/os-documents', '/w1/os-programmes', '/w1/os-statements', '/w1/os-pack',
      '/w1/os-visa', '/w1',
    ]);
    expect(links.map((l) => l.textContent?.trim())).toEqual([
      'Start', 'Inbox', 'Documents', 'Programmes', 'Statements', 'Pack', 'Visa', 'Back to the main menu',
    ]);
    expect(screen.getByRole('link', { name: 'Visa' }).getAttribute('aria-current')).toBe('page');
    fireEvent.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.queryByRole('navigation')).toBeNull();
  });
});
