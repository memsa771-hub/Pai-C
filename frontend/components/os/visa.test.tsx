import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { PackView } from './pack';
import { VisaChoice, VisaFunds } from './visa-funds';
import { asPack, fundsLine, type OsFunds, type OsVisa } from '@/lib/os-visa';
import { workspaceApi } from '@/lib/api';

// Fictional values only.
function funds(over: Partial<OsFunds> = {}): OsFunds {
  return {
    required: 11904, base: 11904, months: 12, reduction: 0, currency_label: 'XYZ', status: 'unconfirmed',
    quote: 'yearly amount', url: 'https://embassy.example/funds', ...over,
  };
}

function visa(over: Partial<OsVisa> = {}): OsVisa {
  return {
    programme_ref: 'p1', name: 'MSc Example', university: 'Uni Sample', status: 'ready', version: 1, approved: false,
    manifest_sha256: 'a'.repeat(64), route_value: 'direct',
    instructions: [{ n: 1, text: 'Open a blocked account.', source_url: 'https://embassy.example/s9', unconfirmed: [] }],
    fees: [],
    checklist: [
      { key: 'admission', label: 'Admission letter', kind: 'document', state: 'ready', ticked: false, reasons: [],
        source: 'default', document_id: 1, tickable: false },
      { key: 'blocked_account', label: 'Blocked account confirmation', kind: 'document', state: 'needs_action',
        ticked: false, reasons: ['the amount is below what you need: 11904 XYZ'], source: 'default', document_id: 2,
        tickable: false },
    ],
    after_approval: [{ key: 'visa_fee_paid', label: 'Paid the visa fee', note: 'Pay the visa fee when the portal asks, then tick this.',
                       ticked: false }],
    data_sheet: [],
    files: [{ key: 'admission', sha256: 'b'.repeat(64), filename: 'admission.pdf', size: 1000, pages: 1 }],
    funds: funds(),
    choice: { programme_ref: null, reduction: 0, preselected: 'p1' },
    programmes: [{ programme_ref: 'p1', name: 'MSc Example', university: 'Uni Sample' },
                 { programme_ref: 'p2', name: 'MSc Other', university: 'Uni Two' }],
    ...over,
  };
}

const noop = () => {};

function fundsBox(f: OsFunds | null, busy = false): string {
  return renderToStaticMarkup(<VisaFunds funds={f} busy={busy} onReduction={noop} />);
}

function file(v: OsVisa): string {
  return renderToStaticMarkup(
    <PackView pack={asPack(v)} busy={false} noun="visa file" notice="You apply and pay yourself. We never send anything for you."
              onTick={noop} onAdd={noop} onApprove={noop} onDownload={noop} onRebuild={noop} onDetails={noop} />,
  );
}

describe('VisaFunds', () => {
  it('shows the amount and label, the status, the source link and the reduction input', () => {
    const html = fundsBox(funds());
    expect(html).toContain('11904');
    expect(html).toContain('XYZ');
    expect(html).toContain('unconfirmed');
    expect(html).toContain('href="https://embassy.example/funds"');
    expect(html).toMatch(/<input[^>]*type="number"/);
  });

  it('says "not confirmed yet" when the amount is missing', () => {
    expect(fundsLine(funds({ required: null, base: null, status: 'missing', url: null }))).toBe('not confirmed yet');
    expect(fundsBox(funds({ required: null, base: null, status: 'missing', url: null }))).toContain('not confirmed yet');
    expect(fundsBox(null)).toContain('not confirmed yet');
  });

  it('shows the reduction taken off', () => {
    expect(fundsLine(funds({ required: 9904, reduction: 2000 }))).toBe('9904 XYZ');
    expect(fundsBox(funds({ required: 9904, reduction: 2000 }))).toContain('2000');
  });
});

describe('VisaChoice', () => {
  it('lists the plan programmes and marks the one the file is for', () => {
    const html = renderToStaticMarkup(<VisaChoice visa={visa()} busy={false} onChoose={noop} />);
    expect(html).toContain('Uni Sample · MSc Example');
    expect(html).toContain('Uni Two · MSc Other');
    expect(html).toMatch(/<option[^>]*value="p1"[^>]*selected=""/);
    expect(html).toContain('admitted');
  });

  it('asks for a choice when there is none', () => {
    const html = renderToStaticMarkup(
      <VisaChoice visa={visa({ programme_ref: null, status: 'no_choice', choice: { programme_ref: null, reduction: 0,
                                                                                  preselected: null } })}
                  busy={false} onChoose={noop} />);
    expect(html).toContain('Choose the programme');
  });
});

// Slice 9 Task 11: `walk:S1:visa_admitted_label_one_only`. Fictional programmes only.
describe('VisaChoice with two admissions', () => {
  const two = visa({ programme_ref: null, status: 'no_choice',
                     choice: { programme_ref: null, reduction: 0, preselected: null, admitted: ['p1', 'p2'] } });

  it('marks every admitted programme', () => {
    const html = renderToStaticMarkup(<VisaChoice visa={two} busy={false} onChoose={noop} />);
    expect(html).toContain('Uni Sample · MSc Example (admitted)');
    expect(html).toContain('Uni Two · MSc Other (admitted)');
  });

  it('asks which one before anything is built, with nothing chosen', () => {
    const html = renderToStaticMarkup(<VisaChoice visa={two} busy={false} onChoose={noop} />);
    expect(html).toContain('You were admitted to more than one programme');
    expect(html).toMatch(/<option[^>]*value=""[^>]*selected=""/);
  });

  it('once chosen, says which one it is for and still marks both', () => {
    const chosen = visa({ choice: { programme_ref: 'p2', reduction: 0, preselected: null, admitted: ['p1', 'p2'] },
                          programme_ref: 'p2' });
    const html = renderToStaticMarkup(<VisaChoice visa={chosen} busy={false} onChoose={noop} />);
    expect(html).toMatch(/<option[^>]*value="p2"[^>]*selected=""/);
    expect(html).not.toContain('You were admitted to more than one programme');
    expect((html.match(/\(admitted\)/g) ?? []).length).toBe(2);
  });
});

describe('the visa file', () => {
  it('says to check the list against the embassy portal', () => {
    const html = renderToStaticMarkup(<VisaChoice visa={visa()} busy={false} onChoose={noop} />);
    expect(html).toContain("check it against the embassy portal&#x27;s own list");
  });

  it('says the student applies and pays', () => {
    expect(file(visa())).toContain('You apply and pay yourself. We never send anything for you.');
    expect(file(visa())).not.toContain('You submit and pay yourself');
  });

  it('enables Approve only when ready', () => {
    expect(file(visa({ status: 'incomplete' }))).toMatch(/<button[^>]*disabled=""[^>]*>Approve visa file<\/button>/);
    expect(file(visa())).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve visa file<\/button>/);
  });

  it('fits 360 px: no fixed widths or horizontal overflow', () => {
    const html = file(visa()) + fundsBox(funds()) + renderToStaticMarkup(<VisaChoice visa={visa()} busy={false} onChoose={noop} />);
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)/);
    expect(html).toContain('break-words');
  });
});

describe('visa API calls', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('saves the choice and downloads a file with the auth header only', async () => {
    const fetchMock = vi.fn(async (url: string) => (url.includes('/files/')
      ? new Response(new Blob(['%PDF-1.4']), { status: 200, headers: { 'Content-Disposition': 'attachment; filename="a.pdf"' } })
      : new Response(JSON.stringify({ programme_ref: 'p2', reduction: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    await workspaceApi.saveOsVisaChoice({ programme_ref: 'p2' });
    const got = await workspaceApi.downloadOsVisaFile('b'.repeat(64));
    expect(got.filename).toBe('a.pdf');
    const [choiceUrl, choiceInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(choiceUrl).toContain('/v1/os/visa/choice?network=ws-1');
    expect(choiceInit.method).toBe('PUT');
    const [url] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect(url).toContain(`/v1/os/visa/files/${'b'.repeat(64)}?network=ws-1`);
    expect(url).not.toContain('bearer-x');
  });
});

// Slice 9 Task 11 (batch D): applying and paying come after the visa file is approved. Fictional values only.
describe('visa file: after you approve', () => {
  it('lists paying the fee after approving, not as something blocking approval', () => {
    const html = file(visa());
    expect(html).toContain('After you approve');
    expect(html).toContain('Do these once your visa file is approved.');
    expect(html).toContain('Pay the visa fee when the portal asks, then tick this.');
    expect(html).not.toContain('Paid the visa fee (tick');
    expect(file(visa({ status: 'approved', approved: true }))).toContain('Ticking them does not change what you approved.');
  });
});
