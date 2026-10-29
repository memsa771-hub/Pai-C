// @vitest-environment jsdom
/** Audit #11: a direct or reloaded link with ?view=profile or ?view=paths opens
 * that view, not chat. The provider must leave the parameter in the URL: the
 * counselor shell reads it when it mounts, which can be after the provider. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { useState, useEffect } from 'react';
import { LayoutProvider, useLayout } from './layout-context';

vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }));
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

function View() {
  return <p data-testid="view">{useLayout().viewMode}</p>;
}
/** Mounts its child one tick later, as the shell does after auth and data. */
function Later({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  useEffect(() => { setReady(true); }, []);
  return ready ? <>{children}</> : null;
}
function UrlView() {
  return <p data-testid="url">{new URLSearchParams(window.location.search).get('view')}</p>;
}

it.each(['profile', 'paths'])('audit #11: ?view=%s opens that view and survives a reload', (view) => {
  window.history.replaceState({}, '', `/w?view=${view}`);
  const first = render(<LayoutProvider><View /><Later><UrlView /></Later></LayoutProvider>);
  expect(screen.getByTestId('view').textContent).toBe(view);
  expect(screen.getByTestId('url').textContent).toBe(view);  // a late reader still sees it
  first.unmount();
  // Reload: the URL still names the view.
  render(<LayoutProvider><View /></LayoutProvider>);
  expect(screen.getByTestId('view').textContent).toBe(view);
});
