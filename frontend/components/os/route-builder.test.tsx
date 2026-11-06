import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EligibilityCard } from './eligibility-card';
import { RouteBuilder } from './route-builder';
import { InboxList } from './inbox-list';
import copy from '@/components/counselor/workspace/copy.json';
import { changeMessage, isStartPending, startPendingMessage, startRefusalMessage } from '@/lib/os-connect';
import {
  CARD_FOOTER,
  MAX_CHOICES,
  PROVISIONAL_TEXT,
  chipLabel,
  lineText,
  moveChoice,
  requestErrorText,
  swapPrompt,
  toggleChoice,
  type OsCard,
  type OsLine,
  type OsNote,
  type OsRouteProgramme,
} from '@/lib/os-self-serve';

// Fictional programmes and values only.
function line(over: Partial<OsLine>): OsLine {
  return { check: 'grade', status: 'likely_meets', have: 2.2, need: 2.5, provisional: false, needs: [], reason: null,
           sources: [{ field: 'grade_requirement', url: 'https://uni.example/req', status: 'confirmed' }], ...over };
}

const CARD: OsCard = {
  programme_ref: 'p1', verdict: 'likely_below',
  lines: [
    line({ provisional: true }),
    line({ check: 'language:english', status: 'likely_below', have: 6, need: 6.5,
           sources: [{ field: 'english_requirement', url: 'https://uni.example/eng', status: 'unconfirmed' }] }),
    line({ check: 'test', status: 'needs_input', have: null, need: ['GRE'], reason: 'no_proof_type', sources: [] }),
  ],
};

function prog(over: Partial<OsRouteProgramme>): OsRouteProgramme {
  return { ref: 'p1', university: 'Uni X', name: 'Data Science', research_state: 'researched',
           requested_by_student: false, confirmed_facts: 2, card: CARD, ...over };
}

function builder(props: Partial<Parameters<typeof RouteBuilder>[0]> = {}): string {
  return renderToStaticMarkup(
    <RouteBuilder routes={[{ key: 'r1', version: 1, origin: 'AA', destination: 'BB', level: 'master' }]} route="r1"
                  onRoute={() => {}} year={2027} onYear={() => {}} programmes={[prog({})]} choices={[]}
                  onToggle={() => {}} onMove={() => {}} onStart={() => {}} onRequest={() => {}} {...props} />,
  );
}

describe('self-serve helpers', () => {
  it('labels every chip', () => {
    expect(chipLabel('likely_meets')).toBe('likely meets');
    expect(chipLabel('likely_below')).toBe('check this');
    expect(chipLabel('needs_input')).toBe('needs your documents');
    expect(chipLabel(prog({ research_state: 'being_researched', card: null }))).toBe('being researched');
  });

  it('says each line in plain words with its numbers', () => {
    expect(lineText(CARD.lines[1])).toBe('Yours 6 · needs 6.5');
    expect(lineText(CARD.lines[2])).toBe('Needs proof of GRE');
    expect(lineText(line({ status: 'needs_input', have: null, needs: ['transcript'] }))).toBe('Needs your transcript');
    expect(lineText(line({ status: 'needs_input', have: null, reason: 'open_finding' }))).toContain('mismatch');
    expect(lineText(line({ status: 'likely_meets', have: null, need: 'none' }))).toBe('Not required');
    expect(lineText(line({ status: 'unknown', have: null }))).toBe("Not found on the programme's pages yet");
  });

  // Slice 9 Task 11 (`walk:S1:chip_unknown_says_being_researched`): a researched programme whose entry requirements
  // were not found is not "being researched"; the chip says what is missing.
  it('tells a researched programme with no requirements found from one still being researched', () => {
    const unknown = { programme_ref: 'p1', verdict: 'unknown' as const,
                      lines: [line({ status: 'unknown', have: null, check: 'grade' })] };
    expect(chipLabel(prog({ card: unknown }))).toBe('entry requirements not found yet');
    expect(chipLabel(prog({ card: { ...unknown, lines: [] } }))).toBe('entry requirements not found yet');
    expect(chipLabel(prog({ research_state: 'being_researched', card: null }))).toBe('being researched');
    expect(chipLabel(prog({ card: null }))).toBe('being researched');
    expect(chipLabel('unknown')).toBe('not found yet');
    const html = builder({ programmes: [prog({ card: unknown })] });
    expect(html).toContain('>entry requirements not found yet<');
    expect(html).not.toContain('being researched');
  });

  it('caps the choices at 10 and reorders them', () => {
    const ten = Array.from({ length: MAX_CHOICES }, (_, i) => `p${i}`);
    expect(toggleChoice(ten, 'extra')).toEqual(ten);
    expect(toggleChoice(['a', 'b'], 'a')).toEqual(['b']);
    expect(moveChoice(['a', 'b', 'c'], 2, -1)).toEqual(['a', 'c', 'b']);
    expect(moveChoice(['a', 'b'], 0, -1)).toEqual(['a', 'b']);
  });

  it('asks before a swap', () => {
    expect(swapPrompt('Data Science', 'Robotics')).toMatch(/^Swap Data Science for Robotics\?/);
  });

  it('turns a 429 into the daily-limit message', () => {
    expect(requestErrorText(new Error('API 429: {"detail":"at most 3"}'))).toContain('up to 3 programmes a day');
  });
});

describe('EligibilityCard', () => {
  it('shows every line, the provisional sentence, sources with their status and the footer', () => {
    const html = renderToStaticMarkup(<EligibilityCard card={CARD} />);
    expect(html).toContain('>Grade<');
    expect(html).toContain('>English<');
    expect(html).toContain('Yours 6 · needs 6.5');
    expect(html).toContain(PROVISIONAL_TEXT.replace("'", '&#x27;'));
    expect(html).toContain('href="https://uni.example/eng"');
    expect(html).toContain('⚠ unconfirmed');
    expect(html).toContain('✓ checked');
    expect(html).toContain(CARD_FOOTER);
  });

  it('offers suggestions with a Swap button', () => {
    const html = renderToStaticMarkup(
      <EligibilityCard card={CARD} suggestions={[{ programme_ref: 'p2', university: 'Uni Y', name: 'Robotics',
                                                  confirmed_facts: 3 }]} onSwap={() => {}} />);
    expect(html).toContain('Robotics');
    expect(html).toContain('>Swap<');
  });
});

describe('RouteBuilder', () => {
  it('lists programmes with chips and the start button', () => {
    const html = builder({ programmes: [prog({}), prog({ ref: 'p2', name: 'Robotics', card: null,
                                                         research_state: 'being_researched', requested_by_student: true })] });
    expect(html).toContain('Data Science');
    expect(html).toContain('>check this<');
    expect(html).toContain('>being researched<');
    expect(html).toContain('requested by a student');
    expect(html).toContain('Start my plan');
  });

  it('shows the ranked choices and the request form with its error', () => {
    const html = builder({ choices: ['p1'], requestError: requestErrorText(new Error('API 429: x')) });
    expect(html).toContain('1. Data Science');
    expect(html).toContain('Request a programme');
    expect(html).toContain('up to 3 programmes a day');
  });

  it('shows an empty state', () => {
    expect(builder({ programmes: [] })).toContain('No programmes for this route and intake yet');
  });

  it('fits 360 px: no fixed widths or horizontal overflow', () => {
    const html = builder({ programmes: [prog({ name: 'A-very-long-programme-name-without-any-spaces-at-all' })],
                           choices: ['p1'], openRef: 'p1', openCard: CARD });
    // whitespace-nowrap is not checked here: the shared Button has it, and its labels are one or two short words
    expect(html).not.toMatch(/\bw-\[\d+px\]|\bmin-w-\[\d+px\]|overflow-x-(auto|scroll)/);
    expect(html).toContain('<p class="break-words text-sm font-medium">A-very-long-programme-name');
  });
});

describe('InboxList notes', () => {
  const NOTE: OsNote = {
    id: 5, programme_ref: 'p1', verdict: 'likely_below', created_at: '2027-03-01T09:00:00Z',
    payload: { plan_id: 7, programme_ref: 'p1', verdict: 'likely_below', previous: 'likely_meets',
               lines: CARD.lines, suggestions: ['p2'] },
  };

  it('shows an eligibility change with its reason and a Swap for each suggestion', () => {
    const html = renderToStaticMarkup(
      <InboxList items={[]} now={new Date('2027-03-01T10:00:00Z')} onComplete={() => {}} notes={[NOTE]}
                 names={{ p1: 'Data Science', p2: 'Robotics' }} onSwap={() => {}} onReadNote={() => {}} />);
    expect(html).toContain('Eligibility updates');
    expect(html).toContain('Data Science');
    expect(html).toContain('check this');
    expect(html).toContain('Yours 6 · needs 6.5');
    expect(html).toContain('Swap for Robotics');
    expect(html).not.toContain('Nothing to do');
  });
});

// req: R-09, R-07
describe('what the builder says when the Counsellor holds the route', () => {
  const COPY = copy.connect;

  it('route builder 202 shows preparing note and no plan', () => {
    const body = { state: 'preparing' as const, decision_version: 3, note: 'Your plan is being prepared.' };
    expect(isStartPending(body)).toBe(true);
    expect(isStartPending({ plan_id: 1, revision: 1, status: 'active', programmes: [] })).toBe(false);
    const message = startPendingMessage(body, COPY);
    expect(message).toEqual({ text: 'Your plan is being prepared.', tone: 'info' });
    const html = builder({ message });
    expect(html).toContain('Your plan is being prepared.');
    expect(html).toContain('role="status"');
  });

  it('falls back to copy.json when the 202 has no note', () => {
    expect(startPendingMessage({ state: 'unchanged', decision_version: 3, note: null }, COPY).text).toBe(COPY.start.unchanged);
    expect(startPendingMessage({ state: 'preparing', decision_version: 3 }, COPY).text).toBe(COPY.start.preparing);
  });

  it('409 choose_field_first shows note', () => {
    const err = new Error('API 409: {"detail":"choose_field_first","note":"Choose your field first."}');
    const message = startRefusalMessage(err, COPY, '/ws-1');
    expect(message).toEqual({ text: 'Choose your field first.', tone: 'error' });
    expect(builder({ message })).toContain('role="alert"');
  });

  it('409 too_many_places shows its note, or the copy.json line without one', () => {
    expect(startRefusalMessage(new Error('API 409: {"detail":"too_many_places","note":"Too many."}'), COPY, '/w')?.text).toBe('Too many.');
    expect(startRefusalMessage(new Error('API 409: {"detail":"too_many_places"}'), COPY, '/w')?.text).toBe(COPY.start.too_many_places);
  });

  it('adopt_first links to the journey where the adoption offer is', () => {
    const message = startRefusalMessage(new Error('API 409: {"detail":"adopt_first","note":"Keep your plan first."}'), COPY, '/ws-1');
    expect(message).toMatchObject({ text: 'Keep your plan first.', href: '/ws-1', linkLabel: COPY.start.adopt_first_link });
    expect(builder({ message })).toContain('href="/ws-1"');
  });

  it('503 counsellor_unavailable is a temporary error; other errors are not ours', () => {
    expect(startRefusalMessage(new Error('API 503: {"detail":"counsellor_unavailable"}'), COPY, '/w')?.text).toBe(COPY.start.unavailable);
    expect(startRefusalMessage(new Error('API 409: {"detail":{"code":"consent_needed"}}'), COPY, '/w')).toBeNull();
    expect(startRefusalMessage(new Error('API 422: bad'), COPY, '/w')).toBeNull();
    expect(startRefusalMessage(new Error('network down'), COPY, '/w')).toBeNull();
  });

  it('swap and remove: requested, and request_open', () => {
    expect(changeMessage({ state: 'requested', proposal_id: 4 }, undefined, COPY)?.text).toBe(COPY.change.requested);
    expect(changeMessage(undefined, new Error('API 409: {"detail":"request_open"}'), COPY)?.text).toBe(COPY.change.request_open);
    expect(changeMessage({ plan_id: 1 }, undefined, COPY)).toBeNull();
    expect(changeMessage(undefined, new Error('API 409: {"detail":"swap_limit"}'), COPY)).toBeNull();
  });

  it('flags off: no message prop renders no message line', () => {
    const html = builder();
    expect(html).not.toContain('role="status"');
    expect(html).not.toContain('role="alert"');
  });
});
