// @vitest-environment jsdom
// req: R-25
// req: R-42
// req: R-72
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReviewItem, type ReviewActions } from './review-item';
import { highlight, parseValue, quoteRanges, stepsFor, type OsReviewDetail, type OsReviewer } from '@/lib/os-review';

afterEach(cleanup);

// Fictional values only.
const QUOTE = 'Apply by 15 July 2027';
const detail = (over: Partial<OsReviewDetail> = {}, item: Partial<OsReviewDetail['item']> = {}): OsReviewDetail => ({
  item: { id: 7, kind: 'verify', status: 'open', resolution: null, fact_id: 3, subject: '', field: 'deadline_close',
          intake_term: '', intake_year: 2027, owner_ref: '', summary: '', payload: {}, batch_ref: null, join_count: 0,
          opened_by: 'manual', created_at: '2027-03-01T00:00:00Z', closed_at: null, ...item },
  fact: { id: 3, scope: 'programme', ref: 'p1', field: 'deadline_close', value: { date: '2027-07-15' }, quote: QUOTE,
          url: 'https://uni.test/apply', status: 'confirmed', checked_at: '2027-03-01T00:00:00Z', intake_term: '',
          intake_year: 2027, owner_ref: '', fact_class: 'deadline', high_stakes: true, read_method: null, language: null },
  snapshot: { url: 'https://uni.test/apply', fetched_at: '2027-03-01T00:00:00Z', read_method: 'fetch',
              text: `Admissions\n${QUOTE} through the portal.`, truncated: false, quote_found: true },
  files: [], reviews: [], my_review: null, ...over,
});
const who = (role: OsReviewer['role']): OsReviewer => ({ ref: 'r1', display_name: 'R One', role, kind: 'ai', active: true, identity: 'r1' });
const actions = (): ReviewActions => ({
  review: vi.fn().mockResolvedValue(undefined), collect: vi.fn().mockResolvedValue(undefined),
  resolve: vi.fn().mockResolvedValue(undefined), upload: vi.fn().mockResolvedValue(11), openFile: vi.fn(),
});

describe('quote marking', () => {
  it('marks the quote across different white space, and pieces in order', () => {
    const text = 'A  intro\nApply   by 15 July 2027 here. Later: closes\nat noon.';
    expect(highlight(text, QUOTE).filter((s) => s.mark).map((s) => s.text)).toEqual(['Apply   by 15 July 2027']);
    expect(highlight(text, 'Apply by ... noon').filter((s) => s.mark).length).toBe(2);
    expect(quoteRanges('nothing here', QUOTE)).toEqual([]);
    expect(highlight('x', 'q').map((s) => s.mark)).toEqual([false]);
  });

  it('reads JSON back, and says when it is not JSON', () => {
    expect(parseValue('{"a":1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parseValue('{a')).toEqual({ ok: false });
    expect(stepsFor('checker')).toEqual(['check']);
    expect(stepsFor('approver')).toEqual(['approve']);
    expect(stepsFor('admin')).toEqual(['check', 'approve']);
  });
});

describe('review item', () => {
  it('shows the fact, the source and the page with the quote marked', () => {
    const { container } = render(<ReviewItem detail={detail()} reviewer={who('checker')} busy={false} actions={actions()} />);
    expect(screen.getByText(/high-stakes/)).toBeTruthy();
    expect(screen.getByText('The quote is on the page.', { exact: false })).toBeTruthy();
    expect(container.querySelector('mark')?.textContent).toBe(QUOTE);
  });

  it('warns when the quote is not on the page', () => {
    const d = detail();
    d.snapshot!.quote_found = false;
    render(<ReviewItem detail={d} reviewer={who('checker')} busy={false} actions={actions()} />);
    expect(screen.getByText(/NOT found/)).toBeTruthy();
  });

  it('a checker gives a check, an approver an approval', () => {
    const a = actions();
    render(<ReviewItem detail={detail()} reviewer={who('checker')} busy={false} actions={a} />);
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Correct' }));
    expect(a.review).toHaveBeenCalledWith(7, expect.objectContaining({ step: 'check', outcome: 'correct' }));
    cleanup();
    const b = actions();
    render(<ReviewItem detail={detail()} reviewer={who('approver')} busy={false} actions={b} />);
    expect(screen.queryByRole('button', { name: 'Correct' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    expect(b.review).toHaveBeenCalledWith(7, expect.objectContaining({ step: 'approve', outcome: 'approve' }));
  });

  it('wrong, unclear and reject need a note', () => {
    const a = actions();
    render(<ReviewItem detail={detail()} reviewer={who('checker')} busy={false} actions={a} />);
    fireEvent.click(screen.getByRole('button', { name: 'Wrong' }));
    expect(screen.getByRole('alert').textContent).toMatch(/note/);
    expect(a.review).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'The page says August' } });
    fireEvent.click(screen.getByRole('button', { name: 'Wrong' }));
    expect(a.review).toHaveBeenCalledWith(7, expect.objectContaining({ outcome: 'wrong', note: 'The page says August' }));
  });

  it('a correction needs valid JSON and a quote', () => {
    const a = actions();
    render(<ReviewItem detail={detail()} reviewer={who('checker')} busy={false} actions={a} />);
    fireEvent.change(screen.getByLabelText('Corrected value (JSON)'), { target: { value: '{bad' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send correction' }));
    expect(screen.getByRole('alert').textContent).toMatch(/valid JSON/);
    fireEvent.change(screen.getByLabelText('Corrected value (JSON)'), { target: { value: '{"date":"2027-08-15"}' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send correction' }));
    expect(screen.getByRole('alert').textContent).toMatch(/quote/);
    fireEvent.change(screen.getByLabelText('Corrected quote'), { target: { value: 'Apply by 15 August 2027' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send correction' }));
    expect(a.review).toHaveBeenCalledWith(7, expect.objectContaining({
      outcome: 'wrong', corrected_value: { date: '2027-08-15' }, corrected_quote: 'Apply by 15 August 2027' }));
  });

  it('shows no other reviewer before the reviewer has given their own, and no form after', () => {
    render(<ReviewItem detail={detail()} reviewer={who('approver')} busy={false} actions={actions()} />);
    expect(screen.queryByRole('list', { name: 'Reviews' })).toBeNull();
    expect(screen.getByText(/stay hidden until you give yours/)).toBeTruthy();
    cleanup();
    const done = detail({ my_review: { step: 'approve', outcome: 'approve' },
                          reviews: [{ id: 1, reviewer: 'ai_check_1', kind: 'ai', step: 'check', outcome: 'correct',
                                      corrected_value: null, corrected_quote: null, note: null }] });
    render(<ReviewItem detail={done} reviewer={who('approver')} busy={false} actions={actions()} />);
    expect(screen.getByText(/ai_check_1/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.getByText('You gave: approve approve.')).toBeTruthy();
  });

  it('collects a reading with evidence, and not without it', async () => {
    const a = actions();
    render(<ReviewItem detail={detail({}, { kind: 'collect' })} reviewer={who('checker')} busy={false} actions={a} />);
    fireEvent.change(screen.getByLabelText('Exact quote'), { target: { value: QUOTE } });
    fireEvent.click(screen.getByRole('button', { name: 'Save reading' }));
    expect(screen.getByRole('alert').textContent).toMatch(/evidence/);
    fireEvent.change(screen.getByLabelText('Evidence file'), { target: { files: [new File(['x'], 'scan.png', { type: 'image/png' })] } });
    await waitFor(() => expect(screen.getByText(/scan.png uploaded/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'Save reading' }));
    expect(a.upload).toHaveBeenCalled();
    expect(a.collect).toHaveBeenCalledWith(7, expect.objectContaining({ quote: QUOTE, evidence_file_id: 11 }));
  });

  it('closes other items with a note, and shows a closed item as closed', () => {
    const a = actions();
    render(<ReviewItem detail={detail({ fact: null, snapshot: null }, { kind: 'suspect_domain', summary: 'asks for fees' })}
                       reviewer={who('checker')} busy={false} actions={a} />);
    const ok = screen.getByRole('button', { name: 'Resolved' }) as HTMLButtonElement;
    expect(ok.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'looked' } });
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(a.resolve).toHaveBeenCalledWith(7, 'dismissed', 'looked');
    cleanup();
    render(<ReviewItem detail={detail({}, { status: 'closed', resolution: 'verified' })} reviewer={who('checker')} busy={false} actions={a} />);
    expect(screen.getByText('Closed: Verified')).toBeTruthy();
    expect(screen.queryByRole('form', { name: 'Your review' })).toBeNull();
  });

  it('opens an evidence file', () => {
    const a = actions();
    const d = detail({ files: [{ id: 5, filename: 'notice.pdf', content_type: 'application/pdf', size: 10, uploaded_by: 'amina' }] });
    render(<ReviewItem detail={d} reviewer={who('checker')} busy={false} actions={a} />);
    fireEvent.click(screen.getByRole('button', { name: 'notice.pdf' }));
    expect(a.openFile).toHaveBeenCalledWith(5);
  });
});
