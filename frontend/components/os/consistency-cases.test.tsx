// @vitest-environment jsdom
// req: R-05
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ConsistencyCases } from './consistency-cases';
import { isMissingEndpoint, type OsConsistencyCase } from '@/lib/os-consistency';

afterEach(cleanup);

// Fictional values only.
const kase: OsConsistencyCase = {
  id: 7, student_ref: 'stu-1', rule: 2, plan_id: 41, codes: ['contract_hash', 'export_hash'], status: 'open',
  resolution: null, first_seen_at: '2027-03-01T21:00:00Z', last_seen_at: '2027-03-02T21:00:00Z', resolved_at: null,
};

describe('consistency cases', () => {
  it('shows the rule, the codes, the student, the plan and both times', () => {
    render(<ConsistencyCases cases={[kase]} busy={false} onResolve={() => {}} />);
    expect(screen.getByRole('heading', { name: 'Consistency checks' })).toBeTruthy();
    expect(screen.getByText('Rule 2: Plan and decision')).toBeTruthy();
    expect(screen.getByText('contract hash, export hash')).toBeTruthy();
    expect(screen.getByText(/Student stu-1 · plan 41 · first seen/)).toBeTruthy();
    expect(screen.getByText(/last seen/)).toBeTruthy();
  });

  it('shows a dash when the case has no plan', () => {
    render(<ConsistencyCases cases={[{ ...kase, plan_id: null }]} busy={false} onResolve={() => {}} />);
    expect(screen.getByText(/plan — ·/)).toBeTruthy();
  });

  it('resolves with a note, and not without one', () => {
    const onResolve = vi.fn();
    render(<ConsistencyCases cases={[kase]} busy={false} onResolve={onResolve} />);
    const button = screen.getByRole('button', { name: 'Resolve' }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Note for check 7'), { target: { value: ' Looked at it. ' } });
    fireEvent.click(button);
    expect(onResolve).toHaveBeenCalledWith(7, 'Looked at it.');
  });

  it('shows an empty state', () => {
    render(<ConsistencyCases cases={[]} busy={false} onResolve={() => {}} />);
    expect(screen.getByText('No open consistency checks.')).toBeTruthy();
  });

  it('treats a 404 from the endpoint as "not part of this deployment"', () => {
    expect(isMissingEndpoint(new Error('API 404: {"detail":"Not Found"}'))).toBe(true);
    expect(isMissingEndpoint(new Error('API 401: admin token required'))).toBe(false);
    expect(isMissingEndpoint('API 404')).toBe(false);
  });
});
