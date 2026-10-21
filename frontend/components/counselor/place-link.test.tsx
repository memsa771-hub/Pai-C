// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { PlaceLink } from './place-link';
afterEach(cleanup);
it('links to a known workspace view by its student-facing name', () => {
  window.history.replaceState({}, '', '/my-space?view=threads');
  const moved = vi.fn();
  window.addEventListener('popstate', moved);
  render(<PlaceLink place="files" />);
  fireEvent.click(screen.getByRole('button', { name: 'Documents' }));
  expect(window.location.search).toBe('?view=files');
  expect(moved).toHaveBeenCalledOnce();
  window.removeEventListener('popstate', moved);
});
it('renders nothing for a place the workspace does not have', () => {
  const { container } = render(<PlaceLink place="operator-console" />);
  expect(container.innerHTML).toBe('');
});
