import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { StatementEditor } from './statement-editor';
import { StatementInterview } from './statement-interview';
import { StatementProgrammes } from './statement-programmes';
import { workspaceApi } from '@/lib/api';
import {
  countLabel,
  kindLabel,
  overBy,
  programmeNames,
  progressLabel,
  rulesLabel,
  segments,
  shortHash,
  statusLabel,
  type OsInterviewItem,
  type OsProgrammeRules,
  type OsStatement,
} from '@/lib/os-statements';

// Merge pai-c + pai-os: on pai-c the bearer is a fresh Firebase ID token (lib/auth/service currentIdToken), and
// configure()'s third argument only marks the client signed in. Stand in the token these tests expect.
vi.mock('@/lib/auth/service', async (original) => ({
  ...(await original<typeof import('@/lib/auth/service')>()),
  currentIdToken: async () => 'bearer-x',
}));

// Fictional values only.
function q(over: Partial<OsInterviewItem>): OsInterviewItem {
  return { id: 'field_why', prompt: 'Why this field?', hint: 'A moment that got you interested.', required: true,
           answer: '', follow_up: false, ...over };
}

const ITEMS = [
  q({ answer: 'Traffic data.' }),
  q({ id: 'key_project', prompt: 'Your key project?', hint: '' }),
  q({ id: 'anything_else', prompt: 'Anything else?', required: false, hint: '' }),
  q({ id: 'followup:1', prompt: 'Which tools did you use?', hint: '', follow_up: true }),
];

const SHA = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2';

function stmt(over: Partial<OsStatement> = {}): OsStatement {
  return {
    id: 3, kind: 'sop', programme_ref: null, status: 'draft', approval: null,
    version: { number: 2, text: 'Traffic data got me into data science. I won the Gold Medal in 2019.', author: 'writer',
               words: 13, critic: { scores: { Motivation: 4 }, fixes: ['Say more about the project'], ok: false },
               flags: ['Gold Medal', '2019'], limit_words: 10, created_at: '2026-10-22T08:00:00Z' },
    ...over,
  };
}

function editor(s: OsStatement): string {
  return renderToStaticMarkup(<StatementEditor statement={s} onSave={() => {}} onRewrite={() => {}} onApprove={() => {}} />);
}

describe('statement helpers', () => {
  it('counts against the limit', () => {
    expect(countLabel(812, 1000)).toBe('812 / 1,000 words');
    expect(countLabel(5, null)).toBe('5 words');
    expect(overBy(1003, 1000)).toBe('Over by 3 words');
    expect(overBy(1001, 1000)).toBe('Over by 1 word');
    expect(overBy(900, 1000)).toBeNull();
  });

  it('counts the required questions answered', () => {
    expect(progressLabel(ITEMS)).toBe('1 of 2 answered');
  });

  it('splits out every flagged phrase', () => {
    expect(segments('In 2019, and again in 2019.', ['2019'])).toEqual([
      { text: 'In ', flagged: false }, { text: '2019', flagged: true }, { text: ', and again in ', flagged: false },
      { text: '2019', flagged: true }, { text: '.', flagged: false }]);
    expect(segments('No flags.', [])).toEqual([{ text: 'No flags.', flagged: false }]);
    expect(shortHash(SHA)).toBe('a1b2c3d4e5f6');
  });
});

describe('StatementInterview', () => {
  const html = renderToStaticMarkup(<StatementInterview items={ITEMS} onSave={() => {}} />);

  it('shows one question per card with its hint', () => {
    expect(html.match(/<section/g)?.length).toBe(4);
    expect(html.match(/<textarea/g)?.length).toBe(4);
    expect(html).toContain('A moment that got you interested.');
    expect(html).toContain('(optional)');
  });

  it('shows the progress count', () => {
    expect(html).toContain('1 of 2 answered');
  });

  it('puts follow-ups first', () => {
    const order = [...html.matchAll(/data-question="([^"]+)"/g)].map((m) => m[1]);
    expect(order[0]).toBe('followup:1');
    expect(html).toContain('A new question about your draft');
  });
});

describe('StatementEditor', () => {
  it('shows the count and the limit', () => {
    const html = editor(stmt());
    expect(html).toContain('14 / 10 words');
    expect(html).toContain('Over by 4 words');
  });

  it('highlights flagged phrases', () => {
    const html = editor(stmt());
    expect(html).toContain('We could not find this in your answers or profile');
    expect(html).toMatch(/<mark[^>]*>Gold Medal<\/mark>/);
    expect(html).toMatch(/<mark[^>]*>2019<\/mark>/);
  });

  it("shows the reviewer's notes", () => {
    expect(editor(stmt())).toContain('Say more about the project');
  });

  it('shows the approved version and short hash', () => {
    const html = editor(stmt({ status: 'approved', approval: { version: 2, sha256: SHA, approved_at: '2026-10-22T09:00:00Z' } }));
    expect(html).toContain('Approved: version 2');
    expect(html).toContain('a1b2c3d4e5f6');
    expect(html).not.toContain(SHA);
    expect(html).toContain('This is the text that goes in your application');
  });

  it('has Save, Write again and Approve this version', () => {
    const html = editor(stmt());
    for (const label of ['Save', 'Write again', 'Approve this version']) expect(html).toContain(`>${label}</button>`);
  });

  it('fits 360 px: no fixed widths or horizontal overflow', () => {
    const long = 'a-very-long-word-without-any-spaces-at-all-that-a-student-might-paste-from-a-website';
    const html = editor(stmt({ version: { ...stmt().version!, text: long, flags: [long] } }))
      + renderToStaticMarkup(<StatementInterview items={[q({ prompt: long })]} onSave={() => {}} />);
    const ours = html.replace(/<button data-slot="button"[^>]*>/g, '<button>'); // the shared Button's own classes
    expect(ours).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)|whitespace-nowrap/);
    expect(html).toContain('break-words');
    expect(html).toContain('max-w-md');
  });
});

describe('statements API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('saves an answer with PUT and the bearer', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ saved: true, drafting: 0 }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    expect(await workspaceApi.saveOsAnswer('followup:1', 'Python.')).toEqual({ saved: true, drafting: 0 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/v1/os/statements/answers/followup%3A1?network=ws-1');
    expect(init.method).toBe('PUT');
    expect(new Headers(init.headers).get('Authorization')).toBe('Bearer bearer-x');
    expect(JSON.parse(init.body as string)).toEqual({ answer: 'Python.' });
  });

  it('saves pasted rules (204, no body)', async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    workspaceApi.configure('ws-1', '', 'bearer-x');
    await workspaceApi.saveOsStatementRules('p1', { prompt: 'Why us?', limit_words: 600 });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain('/v1/os/statements/rules/p1?network=ws-1');
    expect(init.method).toBe('PUT');
  });
});

describe('StatementProgrammes', () => {
  const rules = (over: Partial<OsProgrammeRules>): OsProgrammeRules => ({
    programme_ref: 'p1', needed: true, limit_words: 1000, limit_chars: null, prompt: 'Why this programme?',
    source: 'research', status: 'confirmed', ...over,
  });
  const render = (programmes: OsProgrammeRules[], statements: OsStatement[] = []) => renderToStaticMarkup(
    <StatementProgrammes programmes={programmes} statements={statements} onDraft={() => {}} onPaste={() => {}} />);

  it('offers the programme statement only when the programme asks for one', () => {
    const html = render([rules({}), rules({ programme_ref: 'p2', needed: false, source: 'default', prompt: null })]);
    expect(html.match(/Write the statement for this programme/g)?.length).toBe(1);
    expect(html).toContain("Asks for its own statement: 1,000 words (from the programme&#x27;s pages)");
    expect(html).toContain('Uses your main statement');
    expect(html).toContain('Its question: Why this programme?');
  });

  it('hides the button once that statement exists, and offers a paste where research found nothing', () => {
    const html = render([rules({ source: 'default', needed: false, prompt: null })],
                        [stmt({ programme_ref: 'p1' })]);
    expect(html).not.toContain('Write the statement for this programme');
    expect(html).toContain('Paste its question');
    expect(render([rules({ programme_ref: 'p3' })], [stmt({ programme_ref: 'p3' })]))
      .not.toContain('Write the statement for this programme');
  });

  it('labels unconfirmed research and pasted rules', () => {
    expect(rulesLabel(rules({ status: 'unconfirmed' }))).toContain('not yet confirmed');
    expect(rulesLabel(rules({ source: 'student', limit_words: null, limit_chars: 4000 })))
      .toBe('Asks for its own statement: 4,000 characters (from what you pasted)');
  });

  // Slice 9 Task 11 (`walk:S1:statement_programmes_raw_refs`): programmes by name, never by internal ref.
  it('names each programme, with its university, and never shows the ref', () => {
    const html = render([rules({ programme_ref: 'ovgu-x', name: 'MSc Example', university: 'Uni Sample' }),
                         rules({ programme_ref: 'p-unnamed', needed: false, source: 'default', prompt: null })]);
    expect(html).toContain('>MSc Example<');
    expect(html).toContain('Uni Sample');
    expect(html).not.toContain('>ovgu-x<');
    expect(html).not.toContain('>p-unnamed<');
    expect(html).toContain('A programme in your plan');
  });

  it('names a programme statement by its programme', () => {
    const names = programmeNames([rules({ programme_ref: 'ovgu-x', name: 'MSc Example' })]);
    expect(kindLabel('sop', 'ovgu-x', names)).toBe('Statement of purpose for MSc Example');
    expect(kindLabel('sop', 'gone', names)).toBe('Statement of purpose for one of your programmes');
    expect(kindLabel('sop', null, names)).toBe('Statement of purpose');
    const editor = renderToStaticMarkup(
      <StatementEditor statement={stmt({ programme_ref: 'ovgu-x' })} names={names} onSave={() => {}}
                       onRewrite={() => {}} onApprove={() => {}} />);
    expect(editor).toContain('Statement of purpose for MSc Example');
    expect(editor).not.toContain('ovgu-x');
  });

  it('labels a budget pause', () => {
    expect(statusLabel(stmt({ status: 'budget' }))).toContain('budget is used up');
  });
});
