// @vitest-environment jsdom
// req: R-35
// req: R-66
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { CoverageReport } from './coverage-report';
import { failingFromError, listProgress, workloadLine, type OsCoverage } from '@/lib/os-coverage';

afterEach(cleanup);

// Fictional values only.
const report = (over: Partial<OsCoverage> = {}): OsCoverage => ({
  intake: { id: 1, region: 'r_one', family: 'undergrad', term: 'fall', year: 2027, state: 'open', gate_passed_at: null },
  green: false,
  readings: [
    { gate: 'a', title: 'Denominator', green: true, checked: 1, items: [] },
    { gate: 'b', title: 'Floor', green: false, checked: 1,
      items: [{ code: 'missing', subject: 'inst:one p1 deadline_close', detail: '' }] },
    { gate: 'c', title: 'Rest', green: true, checked: 2, items: [] },
    { gate: 'd', title: 'No info', green: true, checked: 0, items: [] },
  ],
  rows: [{ institution_type: 'university', institutions: 2, listed: 1, researched: 0, verified: 1,
           lists: [{ list_id: 'list:a', name: 'Alpha list', region: 'national', published: 4, loaded: 2, count_confirmed: true }],
           hs_verified: 3, hs_not_confirmed: 1, hs_missing: 2, not_readable: 1 }],
  suspect_domains: ['odd.alpha.test'], open_review_items: { verify: 2 },
  workload: { institutions: 2, high_stakes_facts: 6, high_stakes_per_institution: 3, not_verified: 3, checks_needed: 12,
              checks_left: 6, rows_per_hour: null, hours_left: null, days_left: null },
  ...over,
});

describe('coverage report', () => {
  it('shows red readings with their failing items, and no way to go current', () => {
    render(<CoverageReport report={report()} busy={false} refused={null} onMakeCurrent={vi.fn()} />);
    expect(screen.getByTestId('gate-overall').textContent).toContain('Gate red');
    expect(screen.getByText(/Missing: inst:one p1 deadline_close/)).toBeTruthy();
    expect((screen.getByRole('button', { name: /Make this intake current/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Alpha list: 2 of 4 loaded \(50%\)/)).toBeTruthy();
    expect(screen.getByText(/odd.alpha.test/)).toBeTruthy();
    expect(screen.getByTestId('workload').textContent).toContain('no review rate measured yet');
  });

  it('lets a green open intake be made current, and only an open one', () => {
    const onMake = vi.fn();
    const green = report({ green: true, readings: report().readings.map((r) => ({ ...r, green: true, items: [] })) });
    const { rerender } = render(<CoverageReport report={green} busy={false} refused={null} onMakeCurrent={onMake} />);
    fireEvent.click(screen.getByRole('button', { name: /Make this intake current/ }));
    expect(onMake).toHaveBeenCalledOnce();
    rerender(<CoverageReport report={{ ...green, intake: { ...green.intake, state: 'current' } }} busy={false}
                             refused={null} onMakeCurrent={onMake} />);
    expect(screen.queryByRole('button', { name: /Make this intake current/ })).toBeNull();
  });

  it('says when the server refused', () => {
    render(<CoverageReport report={report()} busy={false} refused={[{ code: 'missing', subject: 'x', detail: '' }]}
                           onMakeCurrent={vi.fn()} />);
    expect(screen.getByRole('alert').textContent).toContain('1 item(s) still fail');
  });
});

describe('helpers', () => {
  it('reads list progress and the workload', () => {
    expect(listProgress({ list_id: 'l', name: 'n', region: null, published: null, loaded: 3, count_confirmed: false }))
      .toBe('3 loaded, no published count');
    expect(workloadLine({ institutions: 1, high_stakes_facts: 1, high_stakes_per_institution: 1, not_verified: 4,
                          checks_needed: 2, checks_left: 8, rows_per_hour: 2, hours_left: 2, days_left: 0.3 }))
      .toBe('4 rows left, 8 checks; about 2 h at 2 rows/h (0.3 working days)');
  });

  it('reads the failing items out of a refused call', () => {
    const body = JSON.stringify({ detail: { message: 'red', failing: [{ gate: 'b', code: 'missing', subject: 's', detail: '' }] } });
    expect(failingFromError(new Error(`API 409: ${body}`))).toHaveLength(1);
    expect(failingFromError(new Error('API 500: boom'))).toEqual([]);
    expect(failingFromError('x')).toEqual([]);
  });
});
