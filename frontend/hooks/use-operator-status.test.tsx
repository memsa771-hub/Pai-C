// @vitest-environment jsdom
import { it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
import { useOperatorStatus } from './use-operator-status';

vi.mock('@/lib/api', () => ({
  workspaceApi: {
    listOperatorRuns: vi.fn().mockResolvedValue({ runs: [] }),
    getOperatorEventsUrl: () => 'http://api.test/v1/events/stream?target=core',
    mapOperatorRun: (payload: unknown) => payload,
  },
}));

class FakeSource {
  static open: FakeSource[] = [];
  closed = false;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) { FakeSource.open.push(this); }
  close() { this.closed = true; }
}
const live = () => FakeSource.open.filter((s) => !s.closed).length;
let hidden = false;

beforeEach(() => {
  FakeSource.open = [];
  hidden = false;
  vi.stubGlobal('EventSource', FakeSource);
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hidden ? 'hidden' : 'visible') });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Probe({ id }: { id: string }) {
  const run = useOperatorStatus(true) as { status?: string } | null;
  return <span data-testid={id}>{run?.status ?? 'none'}</span>;
}

it('shares one stream across every component in the tab', () => {
  const view = render(<><Probe id="a" /><Probe id="b" /><Probe id="c" /></>);
  expect(live()).toBe(1);
  act(() => FakeSource.open[0].onmessage?.({ data: JSON.stringify({ type: 'workspace.operator.run_updated', payload: { status: 'running', updatedAt: '2026-10-21T10:00:00Z' } }) }));
  for (const id of ['a', 'b', 'c']) expect(view.getByTestId(id).textContent).toBe('running');
  view.unmount();
  expect(live()).toBe(0);
});

it('lets go of the stream while the tab is hidden and reconnects on return', () => {
  render(<Probe id="a" />);
  expect(live()).toBe(1);
  act(() => { hidden = true; document.dispatchEvent(new Event('visibilitychange')); });
  expect(live()).toBe(0);
  act(() => { hidden = false; document.dispatchEvent(new Event('visibilitychange')); });
  expect(live()).toBe(1);
});
