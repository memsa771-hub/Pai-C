// @vitest-environment jsdom
// req: R-28
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { asReportTexts, reportOutcome } from '@/lib/os-report';

const TEXTS = {
  reasons: [{ code: 'wrong_date', label: 'The date is wrong' }, { code: 'other', label: 'Something else' }],
  texts: { report_link: 'Report as wrong', report_title: 'What looks wrong?', report_detail_label: 'Tell us more',
           report_submit: 'Send report', report_thanks: 'Thank you.', report_limit: 'Too many today.', report_failed: 'Could not send.' },
};
const api = vi.hoisted(() => ({ getOsReportTexts: vi.fn(), reportOsSource: vi.fn() }));
vi.mock('@/lib/api', () => ({ workspaceApi: api }));

beforeEach(() => { vi.resetModules(); api.getOsReportTexts.mockReset(); api.reportOsSource.mockReset(); });
afterEach(cleanup);

async function mount() {
  const { ReportLink } = await import('./report-link');
  render(<ReportLink url="https://a.example/x" />);
}

describe('report as wrong', () => {
  it('renders nothing when the server has no texts', async () => {
    api.getOsReportTexts.mockRejectedValue(new Error('API 404'));
    await mount();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.body.querySelector('[data-report-link]')).toBeNull();
    expect(asReportTexts({ reasons: [] })).toBeNull();
  });

  it('sends the chosen reason and the words, and says thanks', async () => {
    api.getOsReportTexts.mockResolvedValue(TEXTS);
    api.reportOsSource.mockResolvedValue({ status: 'received' });
    await mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Report as wrong' }));
    fireEvent.change(screen.getByLabelText('Tell us more'), { target: { value: '  moved to September ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send report' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Thank you.'));
    expect(api.reportOsSource).toHaveBeenCalledWith('https://a.example/x', 'wrong_date', 'moved to September');
  });

  it('says the limit sentence on a 429 and the failure sentence otherwise', async () => {
    expect(reportOutcome(TEXTS.texts, Object.assign(new Error('x'), { status: 429 }))).toBe('Too many today.');
    expect(reportOutcome(TEXTS.texts, new Error('API 429: too_many_reports'))).toBe('Too many today.');
    expect(reportOutcome(TEXTS.texts, new Error('boom'))).toBe('Could not send.');
    expect(reportOutcome(TEXTS.texts, null)).toBe('Thank you.');
  });
});
