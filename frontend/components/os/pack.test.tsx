import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { PackList, PackView } from './pack';
import { PackDetails } from './pack-details';
import { canApprove, packStatusLabel, todoCount, type OsPack } from '@/lib/os-packs';
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
      { key: 'fee_paid', label: 'Paid the fee', kind: 'manual', state: 'manual', ticked: false, reasons: [], source: 'default', document_id: null, tickable: true },
    ],
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
