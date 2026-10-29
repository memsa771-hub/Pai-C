import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { PackList, PackView } from './pack';
import { PackDetails } from './pack-details';
import { approveBlockers, canApprove, packStatusLabel, todoCount, type OsPack } from '@/lib/os-packs';
import { workspaceApi } from '@/lib/api';

// Fictional values only.
function pack(over: Partial<OsPack> = {}): OsPack {
  return {
    programme_ref: 'p1', name: 'MSc Example', university: 'Uni Sample', status: 'ready', version: 2, approved: false,
    manifest_sha256: 'a'.repeat(64), route_value: 'uni_assist',
    instructions: [
      { n: 1, text: 'Create an account and add this programme.', source_url: 'https://portal.example/faq', unconfirmed: [] },
      { n: 2, text: 'Apply before not confirmed yet.', source_url: null, unconfirmed: ['deadline_close'] },
    ],
    fees: [{ label: 'Handling fee', value: '75', status: 'confirmed', source_url: 'https://portal.example/fees' },
           { label: 'Tuition', value: null, status: 'missing', source_url: null }],
    checklist: [
      { key: 'passport', label: 'Passport', kind: 'document', state: 'ready', ticked: false, reasons: [], source: 'default', document_id: 1, tickable: false },
      { key: 'degree', label: 'Degree', kind: 'document', state: 'needs_action', ticked: false,
        reasons: ['Upload a colour scan of the attested copy'], source: 'default', document_id: 2, tickable: true },
      { key: 'sop', label: 'Statement of purpose', kind: 'statement', state: 'missing', ticked: false,
        reasons: ['approve your SOP first'], source: 'default', document_id: null, tickable: false },
      { key: 'added:1', label: 'Module descriptions', kind: 'manual', state: 'manual', ticked: false, reasons: [], source: 'student', document_id: null, tickable: true },
    ],
    after_approval: [{ key: 'fee_paid', label: 'Paid the application fee', note: 'Pay the application fee in the portal, then tick this.', ticked: false }],
    data_sheet: [
      { section: 'Personal details', key: 'surname', label: 'Surname', value: 'KHAN', source: 'document', document_id: 1, gap: false, hint: '', entered: false },
      { section: 'Contact', key: 'phone', label: 'Phone', value: null, source: null, document_id: null, gap: true, hint: '', entered: true },
    ],
    files: [{ key: 'passport', sha256: 'b'.repeat(64), filename: 'passport.pdf', size: 1200, pages: 1 },
            { key: 'data_sheet', sha256: 'c'.repeat(64), filename: 'data-sheet.pdf', size: 900, pages: 1 }],
    ...over,
  };
}

const noop = () => {};

function view(p: OsPack): string {
  return renderToStaticMarkup(
    <PackView pack={p} busy={false} onTick={noop} onAdd={noop} onApprove={noop} onDownload={noop}
              onRebuild={noop} onDetails={noop} />,
  );
}

describe('pack helpers', () => {
  it('labels every status, counting what is left to do', () => {
    expect(packStatusLabel(pack({ status: 'building' }))).toBe('being prepared…');
    expect(packStatusLabel(pack({ status: 'incomplete' }))).toBe('3 to do');
    expect(packStatusLabel(pack({ status: 'ready' }))).toBe('ready to approve');
    expect(packStatusLabel(pack({ status: 'approved', approved: true }))).toBe('approved ✓');
    expect(packStatusLabel(pack({ status: 'failed' }))).toBe('could not be prepared');
    expect(todoCount(pack())).toBe(3); // degree, sop, and the unticked manual item
  });

  it('allows approval only for a ready, unapproved pack', () => {
    expect(canApprove(pack({ status: 'ready' }))).toBe(true);
    expect(canApprove(pack({ status: 'incomplete' }))).toBe(false);
    expect(canApprove(pack({ status: 'building' }))).toBe(false);
    expect(canApprove(pack({ status: 'approved', approved: true }))).toBe(false);
  });
});

describe('PackList', () => {
  it('shows the empty state', () => {
    expect(renderToStaticMarkup(<PackList packs={[]} onOpen={noop} />)).toContain('No programmes in your plan yet');
  });

  it('lists each programme with its status', () => {
    const html = renderToStaticMarkup(<PackList packs={[pack(), pack({ programme_ref: 'p2', status: 'building' })]} onOpen={noop} />);
    expect(html).toContain('Uni Sample · MSc Example');
    expect(html).toContain('ready to approve');
    expect(html).toContain('being prepared…');
  });
});

describe('PackView', () => {
  it('says the student submits and pays', () => {
    expect(view(pack())).toContain('You submit and pay yourself. We never send anything for you.');
  });

  it('shows each instruction step with its source link', () => {
    const html = view(pack());
    expect(html).toContain('Create an account and add this programme.');
    expect(html).toContain('href="https://portal.example/faq"');
    expect(html).toContain('not confirmed yet');
  });

  it('shows fees with their status', () => {
    const html = view(pack());
    expect(html).toContain('Handling fee');
    expect(html).toContain('75');
    expect(html).toContain('confirmed');
    expect(html).toContain('not known yet');
  });

  it('marks checklist items with their reasons', () => {
    const html = view(pack());
    expect(html).toContain('Upload a colour scan of the attested copy');
    expect(html).toContain('approve your SOP first');
    expect(html).toMatch(/type="checkbox"/);
  });

  it('offers a download only for items with a file', () => {
    const html = view(pack());
    expect(html.match(/>Download</g)?.length).toBe(2); // the passport and the data sheet
  });

  it('puts a copy button on each value and highlights gaps with the details link', () => {
    const html = view(pack());
    expect(html).toContain('KHAN');
    expect(html.match(/>Copy</g)?.length).toBe(1); // only values can be copied
    expect(html).toContain('missing');
    expect(html).toContain('A few more details');
  });

  it('enables Approve only when the pack is ready', () => {
    expect(view(pack({ status: 'incomplete' }))).toMatch(/<button[^>]*disabled=""[^>]*>Approve pack<\/button>/);
    expect(view(pack())).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve pack<\/button>/);
    expect(view(pack({ status: 'approved', approved: true }))).toContain('Approved ✓');
  });

  it('fits 360 px: no fixed widths or horizontal overflow', () => {
    const html = view(pack());
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)/);
    expect(html).toContain('break-words');
  });
});

describe('PackDetails', () => {
  it('shows only the fields the student types', () => {
    const html = renderToStaticMarkup(<PackDetails rows={pack().data_sheet} busy={false} onSave={noop} onBack={noop} />);
    expect(html).toContain('Phone');
    expect(html).not.toContain('Surname');
    expect(html.match(/<input/g)?.length).toBe(1);
  });
});

describe('pack API calls', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('downloads a file with the auth header, never a token in the URL', async () => {
    const fetchMock = vi.fn(async () => new Response(new Blob(['%PDF-1.4']), {
      status: 200, headers: { 'Content-Disposition': 'attachment; filename="passport.pdf"' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    const got = await workspaceApi.downloadOsPackFile('p1', 'b'.repeat(64));
    expect(got.filename).toBe('passport.pdf');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain(`/v1/os/packs/p1/files/${'b'.repeat(64)}?network=ws-1`);
    expect(url).not.toContain('bearer-x');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer bearer-x');
  });
});

// Slice 9 Task 11: the rehearsal walkthroughs' pack findings. Fictional values only.
describe('ticks before approval (walk:S1:ticks_before_approve)', () => {
  it('says ticks are needed before Approve, and lists what is left under a disabled Approve', () => {
    const html = view(pack({ status: 'incomplete' }));
    expect(html).toContain('You can approve only when every item has a ✓ or a tick');
    expect(html).toContain('Before you can approve:');
    expect(html).toContain('Module descriptions (tick it once you have done it)');
    expect(html).toContain('Statement of purpose');
    expect(html).not.toContain('Passport (tick');  // a ready item is not listed
  });

  it('lists nothing to do once the pack can be approved', () => {
    const ready = pack({ checklist: pack().checklist.map((i) => ({ ...i, state: i.state === 'manual' ? 'manual' : 'ready',
                                                                    ticked: true })) });
    expect(view(ready)).not.toContain('Before you can approve:');
    expect(approveBlockers(ready)).toEqual([]);
  });
});

describe('data sheet at 375 px (walk:S1:datasheet_label_overlap)', () => {
  it('puts each label on its own line above its value, and lets a long value wrap anywhere', () => {
    const long = pack({ data_sheet: [{ section: 'English', key: 'trf', label: 'IELTS TRF number',
                                       value: '24ZZ00111SAMP101A', source: 'document', document_id: 3, gap: false,
                                       hint: '', entered: false }] });
    const html = view(long);
    const row = /<div class="([^"]*)"><dt[^>]*>IELTS TRF number<\/dt>/.exec(html);
    expect(row).not.toBeNull();
    expect(row![1]).toContain('flex-col');
    expect(html).toMatch(/<span class="[^"]*\[overflow-wrap:anywhere\][^"]*">24ZZ00111SAMP101A<\/span>/);
    expect(html).not.toContain('justify-end');
  });
});

// Slice 9 Task 11 (batch D, ruling): paying and applying come after approval. Fictional values only.
describe('after you approve', () => {
  it('never lists an after-approval item as blocking approval', () => {
    const p = pack({ checklist: [{ key: 'fee_paid', label: 'Paid the application fee', kind: 'manual', state: 'manual',
                                   ticked: false, reasons: [], source: 'default', document_id: null, tickable: true,
                                   after_approval: true }] });
    expect(approveBlockers(p)).toEqual([]);
    expect(todoCount(p)).toBe(0);
  });

  it('shows the steps after approving in their own group, tickable only once approved', () => {
    const before = view(pack());
    expect(before).toContain('After you approve');
    expect(before).toContain('Pay the application fee in the portal, then tick this.');
    expect(before).toMatch(/<input type="checkbox" disabled=""[^>]*\/>Paid the application fee/);
    expect(before).not.toContain('Paid the application fee (tick');  // not a blocker
    const after = view(pack({ status: 'approved', approved: true }));
    expect(after).toContain('After you approve');
    expect(after).not.toMatch(/<input type="checkbox" disabled=""[^>]*\/>Paid the application fee/);
  });

  it('shows no such group when there is nothing after approving', () => {
    expect(view(pack({ after_approval: [] }))).not.toContain('After you approve');
    expect(view(pack({ after_approval: undefined }))).not.toContain('After you approve');
  });
});
