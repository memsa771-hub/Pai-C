import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ChangesList } from './changes-list';
import { PausedBanner, ProposalCard } from './proposal-card';
import { SupportList } from './support-list';
import { opText, stepName, type OsProposal, type OsReplanOp, type OsSupportCase } from '@/lib/os-replan';
import { workspaceApi } from '@/lib/api';

// Fictional values only.
const R = 'The programme did not admit you: its remaining steps are removed.';
const NAMES = { 'prog-a': 'MSc Example', 'prog-c': 'MSc Other' };

function proposal(over: Partial<OsProposal> = {}): OsProposal {
  return {
    id: 7, plan_id: 1, status: 'pending', big: true, source: 'rules',
    ops: [{ op: 'cancel_programme', programme_ref: 'prog-a', reason: R }], reasons: [R], revision: null,
    expires_at: '2027-03-08T09:00:00Z', created_at: '2027-03-01T09:00:00Z', answered_at: null, ...over,
  };
}

const noop = () => {};

describe('opText', () => {
  it('words every operation', () => {
    const cases: [OsReplanOp, string][] = [
      [{ op: 'add_task', template_key: 'review_visa_file', programme_ref: null, reason: R }, 'Add the step “Review visa file”'],
      [{ op: 'skip_task', instance_key: 'language_test', reason: R }, 'Skip “Language test”'],
      [{ op: 'cancel_task', instance_key: 'apply@prog-a', reason: R }, 'Remove “Apply” for MSc Example'],
      [{ op: 'cancel_programme', programme_ref: 'prog-a', reason: R }, 'Remove the steps for MSc Example'],
      [{ op: 'reprioritise', instance_key: 'certificates', before: 'language_test', reason: R }, 'Do “Certificates” before “Language test”'],
      [{ op: 'swap_programme', out_ref: 'prog-a', in_ref: 'prog-c', reason: R }, 'Replace MSc Example with MSc Other'],
      [{ op: 'request_from_student', instance_key: 'x', message: 'Please upload it.', reason: R }, 'Please upload it.'],
      [{ op: 'escalate', reason: R }, 'Ask a person to check your plan'],
      [{ op: 'upgrade_playbook', version: 2, reason: R }, 'Move your plan to the newest guide (version 2)'],
    ];
    for (const [op, text] of cases) expect(opText(op, NAMES)).toBe(text);
  });

  it('names a step without its programme or repeat marks', () => {
    expect(stepName('review_visa_file#2')).toBe('Review visa file');
    expect(stepName('apply@prog-a')).toBe('Apply');
  });
});

describe('ProposalCard', () => {
  it('says what, why, by when, with Accept and Decline', () => {
    const html = renderToStaticMarkup(<ProposalCard proposal={proposal()} names={NAMES} busy={false}
                                                    onAccept={noop} onDecline={noop} />);
    expect(html).toContain('We suggest:');
    expect(html).toContain('Remove the steps for MSc Example');
    expect(html).toContain('Why:');
    expect(html).toContain(R);
    expect(html).toContain('>Accept<');
    expect(html).toContain('>Decline<');
    expect(html).toContain('Answer by');
  });

  it('disables both buttons while busy', () => {
    const html = renderToStaticMarkup(<ProposalCard proposal={proposal()} names={NAMES} busy onAccept={noop}
                                                    onDecline={noop} />);
    expect(html.match(/disabled=""/g)?.length).toBe(2);
  });
});

describe('PausedBanner', () => {
  it('says changes are paused', () => {
    expect(renderToStaticMarkup(<PausedBanner />)).toContain('Changes are paused while a person checks your plan.');
  });
});

describe('ChangesList', () => {
  it('lists changes newest first with why', () => {
    const older = { ...proposal({ id: 1, status: 'accepted' }), proposal_id: 1, at: '2027-03-01T09:00:00Z' };
    const newer = { ...proposal({ id: 2, status: 'applied', ops: [{ op: 'escalate', reason: 'A step failed twice: a person will look at it.' }],
                                  reasons: ['A step failed twice: a person will look at it.'] }),
                    proposal_id: 2, at: '2027-03-05T09:00:00Z' };
    const html = renderToStaticMarkup(<ChangesList changes={[older, newer]} names={NAMES} />);
    expect(html.indexOf('Ask a person')).toBeLessThan(html.indexOf('Remove the steps'));
    expect(html).toContain('A step failed twice');
    expect(renderToStaticMarkup(<ChangesList changes={[]} names={NAMES} />)).toContain('No changes yet');
  });
});

describe('SupportList', () => {
  const kase: OsSupportCase = {
    id: 3, plan_id: 1, student_ref: 'stu-1', reason: 'A step failed twice.', event_ids: [4], proposal_id: null,
    status: 'open', resolution: null, created_at: '2027-03-01T09:00:00Z', resolved_at: null, changes_paused: true,
    counsellor_status: null, counsellor_reason: null,
  };

  it('shows sent to the Counsellor', () => {
    const sent = renderToStaticMarkup(<SupportList cases={[{ ...kase, counsellor_status: 'sent',
      counsellor_reason: 'blocking_gap' }]} busy={false} onResolve={noop} />);
    expect(sent).toContain('Sent to the Counsellor (blocking gap)');
    const refused = renderToStaticMarkup(<SupportList cases={[{ ...kase, counsellor_status: 'refused',
      counsellor_reason: 'all_rejected' }]} busy={false} onResolve={noop} />);
    expect(refused).toContain('Refused by the Counsellor (all rejected): still open here');
    expect(refused).toContain('>Resolve<');  // a refused case stays open here
    expect(renderToStaticMarkup(<SupportList cases={[kase]} busy={false} onResolve={noop} />))
      .not.toContain('Counsellor');  // a system problem stays in this inbox only
  });

  it('lists cases and offers a resolve form with unpause', () => {
    const html = renderToStaticMarkup(<SupportList cases={[kase]} busy={false} onResolve={noop} />);
    expect(html).toContain('A step failed twice.');
    expect(html).toContain('paused');
    expect(html).toMatch(/<textarea/);
    expect(html).toMatch(/type="checkbox"/);
    expect(html).toContain('>Resolve<');
  });

  it('shows the empty state', () => {
    expect(renderToStaticMarkup(<SupportList cases={[]} busy={false} onResolve={noop} />)).toContain('No open cases');
  });
});

describe('360 px', () => {
  it('has no fixed widths or horizontal overflow', () => {
    const html = renderToStaticMarkup(<ProposalCard proposal={proposal()} names={NAMES} busy={false} onAccept={noop}
                                                    onDecline={noop} />)
      + renderToStaticMarkup(<ChangesList changes={[]} names={NAMES} />) + renderToStaticMarkup(<PausedBanner />);
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)/);
    expect(html).toContain('break-words');
  });
});

describe('replan API calls', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('accepts with POST and sends the admin token only in its header', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ status: 'accepted', revision: 3, cases: [] }),
                                                     { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    await workspaceApi.acceptOsProposal(7);
    await workspaceApi.getOsSupportCases('admin-secret', 'open');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/v1/os/proposals/7/accept?network=ws-1');
    expect(init.method).toBe('POST');
    const [adminUrl, adminInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(adminUrl).toContain('/v1/os/admin/support?');
    expect(adminUrl).not.toContain('admin-secret');
    expect(new Headers(adminInit.headers).get('X-OS-Admin-Token')).toBe('admin-secret');
  });
});

describe('admin token (final review I12)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('a wrong admin token fails the call without signing the user out', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"admin token required"}', { status: 401 })));
    const { AUTH_INVALID_EVENT } = await import('@/lib/auth/service');
    const signedOut = vi.fn();
    const win = new EventTarget();  // the browser window the app's sign-out listens on
    vi.stubGlobal('window', win);
    win.addEventListener(AUTH_INVALID_EVENT, signedOut);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    await expect(workspaceApi.getOsSupportCases('wrong', 'open')).rejects.toThrow('API 401');
    await expect(workspaceApi.resolveOsSupportCase('wrong', 1, 'x', false)).rejects.toThrow('API 401');
    expect(signedOut).not.toHaveBeenCalled();
  });
});
