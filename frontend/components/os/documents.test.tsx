import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { DocumentList } from './documents';
import { DocumentConfirm } from './document-confirm';
import {
  checkFailedCount,
  docStatusLabel,
  findingText,
  type OsDocType,
  type OsDocument,
  type OsDocField,
  type OsFinding,
} from '@/lib/os-documents';
import { workspaceApi } from '@/lib/api';

// Fictional values only.
const TYPES: OsDocType[] = [
  { key: 'passport', label: 'Passport' },
  { key: 'degree_certificate', label: 'Degree certificate' },
  { key: 'transcript', label: 'Transcript' },
];

function field(over: Partial<OsDocField>): OsDocField {
  return { field: 'surname', value_read: 'KHAN', check: 'ok', reasons: [], value_confirmed: null, ...over };
}

function doc(over: Partial<OsDocument>): OsDocument {
  return {
    id: 1, doc_type: 'passport', filename: 'passport.jpg', status: 'read', detected_type: 'passport', pages: 1,
    error: null, created_at: '2026-10-21T08:00:00Z', read_at: '2026-10-21T08:01:00Z', confirmed_at: null,
    fields: [field({})], findings: [], ...over,
  };
}

const FINDING: OsFinding = {
  id: 9, kind: 'variant', field: 'full_name', status: 'open', resolution: null,
  items: [{ document_id: 1, value: 'MUHAMMAD ALI' }, { document_id: 2, value: 'Mohammad Ali' }],
};

function list(props: Partial<Parameters<typeof DocumentList>[0]> = {}): string {
  return renderToStaticMarkup(
    <DocumentList documents={[]} findings={[]} docTypes={TYPES} onUpload={() => {}} onOpen={() => {}}
                  onResolve={() => {}} onDelete={() => {}} {...props} />,
  );
}

describe('document helpers', () => {
  it('labels every status', () => {
    expect(docStatusLabel(doc({ status: 'uploaded' }))).toBe('waiting to be read');
    expect(docStatusLabel(doc({ status: 'reading' }))).toBe('reading…');
    expect(docStatusLabel(doc({ status: 'read' }))).toBe('read');
    expect(docStatusLabel(doc({ status: 'needs_student' }))).toBe('check the type');
    expect(docStatusLabel(doc({ status: 'confirmed' }))).toBe('confirmed ✓');
    expect(docStatusLabel(doc({ status: 'failed' }))).toBe('could not read');
  });

  it('counts the fields whose check failed', () => {
    const d = doc({ fields: [field({ check: 'check_failed', reasons: ['expired'] }), field({ field: 'x', check: 'missing' }),
                             field({ field: 'y', check: 'check_failed', reasons: ['empty'] })] });
    expect(checkFailedCount(d)).toBe(2);
  });

  it('words a finding with the documents and values', () => {
    const docs = [doc({ id: 1 }), doc({ id: 2, doc_type: 'degree_certificate' })];
    expect(findingText(FINDING, docs, TYPES)).toBe(
      'Your name differs: passport "MUHAMMAD ALI", degree certificate "Mohammad Ali". Which is right?');
    expect(findingText({ ...FINDING, field: 'date_of_birth' }, docs, TYPES)).toContain('Your date of birth differs');
  });
});

describe('DocumentList', () => {
  it('shows the empty state with the upload control', () => {
    const html = list();
    expect(html).toContain('No documents yet');
    expect(html).toContain('type="file"');
    expect(html).toContain('accept="application/pdf,image/jpeg,image/png,image/webp,.jfif"');
    expect(html).toMatch(/<option value="passport"[^>]*>Passport<\/option>/);
    expect(html).toMatch(/<option value="transcript"[^>]*>Transcript<\/option>/);
  });

  it('shows each document with its status and the check-failed count', () => {
    const html = list({
      documents: [
        doc({ fields: [field({ check: 'check_failed', reasons: ['expired'] }), field({ field: 'a', check: 'check_failed' })] }),
        doc({ id: 2, doc_type: 'transcript', status: 'confirmed' }),
        doc({ id: 3, doc_type: 'degree_certificate', status: 'reading' }),
      ],
    });
    expect(html).toContain('Passport');
    expect(html).toContain('⚠ check 2 fields');
    expect(html).toContain('confirmed ✓');
    expect(html).toContain('reading…');
  });

  it('asks about a type mismatch and shows a failed reading with its reason', () => {
    const html = list({
      documents: [doc({ status: 'needs_student', detected_type: 'transcript' }),
                  doc({ id: 2, status: 'failed', error: 'The file could not be read: it may be damaged.' })],
    });
    expect(html).toContain('This looks like a transcript. Is that right?');
    expect(html).toContain('The file could not be read: it may be damaged.');
  });

  it('offers Delete on a document that cannot be opened, so a failed reading is never a dead end', () => {
    const html = list({ documents: [doc({ id: 1, status: 'failed', error: 'We could not read this document.' }),
                                    doc({ id: 2, status: 'uploaded' }), doc({ id: 3, status: 'read' })] });
    expect(html.match(/>Delete<\/button>/g)?.length).toBe(2);  // failed and uploaded; a read one opens instead
    expect(html).toContain('You can delete it and upload the file again.');
  });

  it('shows a finding with a Choose button per value', () => {
    const html = list({ documents: [doc({ id: 1 }), doc({ id: 2, doc_type: 'degree_certificate' })], findings: [FINDING] });
    expect(html).toContain('Your name differs: passport &quot;MUHAMMAD ALI&quot;');
    expect(html).toContain('Choose');
    expect(html).toContain('>MUHAMMAD ALI</button>');
    expect(html).toContain('>Mohammad Ali</button>');
  });

  it('fits 360 px: no fixed widths or horizontal overflow', () => {
    const html = list({ documents: [doc({ filename: 'a-very-long-file-name-without-any-spaces-at-all-from-a-phone.jpg' })],
                        findings: [FINDING] });
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)|whitespace-nowrap/);
    expect(html).toContain('break-words');
    expect(html).toContain('max-w-md');
  });
});

describe('DocumentConfirm', () => {
  const d = doc({
    fields: [
      field({ field: 'surname', value_read: 'KHAN' }),
      field({ field: 'expiry_date', value_read: '2020-01-31', check: 'check_failed',
              reasons: ['expired', 'the expiry date does not match the machine-readable line'] }),
      field({ field: 'tracking_number', value_read: null, check: 'missing' }),
      field({ field: 'cgpa', value_read: 3.7 }),
    ],
  });

  it('says plainly that every value must be checked', () => {
    expect(renderToStaticMarkup(<DocumentConfirm document={d} onConfirm={() => {}} />))
      .toContain('We read this automatically; please check every value.');
  });

  it('makes every field editable, with the value read', () => {
    const html = renderToStaticMarkup(<DocumentConfirm document={d} onConfirm={() => {}} />);
    expect(html.match(/<input/g)?.length).toBe(4);
    expect(html).toContain('value="KHAN"');
    expect(html).toContain('value="3.7"');
    expect(html).toContain('Surname');
    expect(html).toContain('Expiry date');
  });

  it('marks a failed check with its reasons', () => {
    const html = renderToStaticMarkup(<DocumentConfirm document={d} onConfirm={() => {}} />);
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('expired');
    expect(html).toContain('the expiry date does not match the machine-readable line');
    expect(html).toContain('not found on the document');
  });

  it('has one Confirm all button', () => {
    const html = renderToStaticMarkup(<DocumentConfirm document={d} onConfirm={() => {}} />);
    expect(html.match(/Confirm all/g)?.length).toBe(1);
  });
});

describe('uploadOsDocument', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends FormData with the auth header and no JSON content type', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(doc({ status: 'uploaded', fields: [] })), { status: 201 }));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'passport.jpg', { type: 'image/jpeg' });
    const out = await workspaceApi.uploadOsDocument(file, 'passport');
    expect(out.status).toBe('uploaded');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/v1/os/documents?network=ws-1');
    expect(init.method).toBe('POST');
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer bearer-x');
    expect(headers.has('Content-Type')).toBe(false);
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get('doc_type')).toBe('passport');
    expect((body.get('file') as File).name).toBe('passport.jpg');
  });

  it('reports a refused upload with the server reason', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'this file is already uploaded' }),
                                                            { status: 409 })));
    workspaceApi.configure('ws-1', '', 'bearer-x');
    const file = new File([new Uint8Array([1])], 'a.jpg');
    await expect(workspaceApi.uploadOsDocument(file, 'passport')).rejects.toThrow('this file is already uploaded');
  });
});
