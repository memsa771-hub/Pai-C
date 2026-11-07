// @vitest-environment jsdom
import { Suspense } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { I18nProvider } from '@/lib/i18n';
import { workspaceApi } from '@/lib/api';
import copy from '@/components/counselor/workspace/copy.json';
import OsInboxPage from '../../app/[workspaceId]/(os)/os-inbox/page';

vi.mock('@/lib/config', () => ({ OS_UI_ENABLED: true, OS_REHEARSAL_UI: false, OS_FROM_STAGE: 'H' }));
const signedIn = { loading: false, user: { uid: 'u' }, idToken: 't' };  // one object: the page's effect depends on it
vi.mock('@/lib/pai-auth-context', () => ({ usePaiAuth: () => signedIn }));
vi.mock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'ws1' }), useRouter: () => ({ push: vi.fn() }), notFound: vi.fn() }));
vi.mock('@/lib/api', () => ({
  workspaceApi: {
    configure: vi.fn(), getOsInboxAll: vi.fn(), getOsChanges: vi.fn(), getOsProgrammes: vi.fn(), getOsRequests: vi.fn(),
    answerOsRequest: vi.fn(), completeOsInboxItem: vi.fn(),
  },
}));

const params = Object.assign(Promise.resolve({ workspaceId: 'ws1' }), { status: 'fulfilled', value: { workspaceId: 'ws1' } });
const step = { id: 41, instance_key: 'which_is_right@fact:a.b:stated', title: 'Which marks are right?', kind: 'student',
  inbox_kind: 'choose', programme_ref: null, state: 'waiting_student', blocked_reason: null, due_at: null, due_tz: 'UTC',
  provisional: false, estimated: false, slack_days: null, critical: false, citations: [] };
const choice = (over: object) => ({ ref: 'card-1', key: 'a.b', seen: 'tok', choice: 'current', label: 'Saved in PAI', value: 770,
  source: { kind: 'vault', evidence: 'stated', document_ref: null, as_of: null }, ...over });
const asked = { id: 10, task_id: 41, kind: 'which_is_right', need: { kind: 'fact', ref: 'a.b', evidence: 'stated' }, status: 'open',
  due_at: null, due_tz: null, title: null, how: 'Two places say different things.', ref: 'card-1', seen: 'tok',
  allow_new: true, new_label: 'Neither: I will type the right value',
  choices: [choice({}), choice({ choice: 'proposed', label: 'From your document', value: 760 })] };

const show = () => render(<I18nProvider><Suspense fallback={null}><OsInboxPage params={params} /></Suspense></I18nProvider>);

beforeEach(() => {
  vi.mocked(workspaceApi.getOsInboxAll).mockResolvedValue({ items: [step], notes: [], proposals: [] } as never);
  vi.mocked(workspaceApi.getOsChanges).mockRejectedValue(new Error('none'));
  vi.mocked(workspaceApi.getOsProgrammes).mockResolvedValue([]);
  vi.mocked(workspaceApi.getOsRequests).mockResolvedValue([asked] as never);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

// req: R-21
describe('the inbox page and the requests', () => {
  it('an answer names the question it saw, then the inbox is loaded again', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockResolvedValue({ status: 'answered' });
    show();
    fireEvent.click(await screen.findByRole('button', { name: /From your document/ }));
    await waitFor(() => expect(workspaceApi.answerOsRequest).toHaveBeenCalledWith(10, 'proposed', { ref: 'card-1', seen: 'tok' }, undefined));
    await waitFor(() => expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(2));
    expect(workspaceApi.getOsRequests).toHaveBeenCalledTimes(2);
  });

  it('a typed value goes as choice new with the question it saw', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockResolvedValue({ status: 'answered' });
    show();
    fireEvent.change(await screen.findByLabelText('Neither: I will type the right value'), { target: { value: '765' } });
    fireEvent.click(screen.getByRole('button', { name: 'Use this value' }));
    await waitFor(() => expect(workspaceApi.answerOsRequest).toHaveBeenCalledWith(10, 'new', { ref: 'card-1', seen: 'tok' }, 765));
  });

  it('a question that changed shows the server note and loads the new question', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockRejectedValue(
      new Error('API 409: {"detail":"answer_changed","note":"This question changed. Choose once more."}'));
    show();
    fireEvent.click(await screen.findByRole('button', { name: /770/ }));
    expect((await screen.findByRole('alert')).textContent).toBe('This question changed. Choose once more.');
    expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(2);
  });

  it('an unavailable Counsellor says so and keeps the question', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockRejectedValue(new Error('API 503: {"detail":"counsellor_unavailable"}'));
    show();
    fireEvent.click(await screen.findByRole('button', { name: /770/ }));
    expect((await screen.findByRole('alert')).textContent).toContain('PAI cannot take this right now');
    expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(1);
  });

  it('no requests endpoint means today\'s inbox', async () => {
    vi.mocked(workspaceApi.getOsRequests).mockResolvedValue(null);
    vi.mocked(workspaceApi.getOsInboxAll).mockResolvedValue({ items: [{ ...step, instance_key: 'x@1' }], notes: [], proposals: [] } as never);
    show();
    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeTruthy();
    expect(screen.queryByText('Two places say different things.')).toBeNull();
  });

  it('two clicks on the same answer send one, and the old question stays shut until the list is loaded again', async () => {
    let finish: (v: { status: 'answered' }) => void = () => {};
    vi.mocked(workspaceApi.answerOsRequest).mockReturnValue(new Promise((r) => { finish = r; }));
    show();
    const button = await screen.findByRole('button', { name: /760/ });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(screen.getByRole('button', { name: /770/ }));
    expect(workspaceApi.answerOsRequest).toHaveBeenCalledTimes(1);
    finish({ status: 'answered' });
    await waitFor(() => expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(2));
    await waitFor(() => expect((screen.getByRole('button', { name: /760/ }) as HTMLButtonElement).disabled).toBe(false));
  });

  it('still_open loads the list again', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockResolvedValue({ status: 'still_open' } as never);
    show();
    fireEvent.click(await screen.findByRole('button', { name: /760/ }));
    await waitFor(() => expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(2));
  });

  it('a question that is gone says so, loads the list again and moves focus to the message', async () => {
    vi.mocked(workspaceApi.answerOsRequest).mockRejectedValue(new Error('API 404: {"detail":"Not Found"}'));
    show();
    fireEvent.click(await screen.findByRole('button', { name: /760/ }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe(copy.connect.requests.gone);
    expect(workspaceApi.getOsInboxAll).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(document.activeElement).toBe(alert));
  });

  it('the inbox and its requests are loaded together: a failed requests call leaves today\'s inbox', async () => {
    vi.mocked(workspaceApi.getOsRequests).mockRejectedValue(new Error('API 500: boom'));
    vi.mocked(workspaceApi.getOsInboxAll).mockResolvedValue({ items: [{ ...step, instance_key: 'x@1' }], notes: [], proposals: [] } as never);
    show();
    expect(await screen.findByRole('button', { name: 'Confirm' })).toBeTruthy();
  });

  it('a refused Mark as done shows the server sentence', async () => {
    vi.mocked(workspaceApi.getOsRequests).mockResolvedValue(null);
    vi.mocked(workspaceApi.completeOsInboxItem).mockRejectedValue(
      new Error('API 409: {"detail":"This step closes by itself when PAI has what it needs."}'));
    vi.mocked(workspaceApi.getOsInboxAll).mockResolvedValue({ items: [{ ...step, instance_key: 'x@1', inbox_kind: 'act' }], notes: [], proposals: [] } as never);
    show();
    fireEvent.click(await screen.findByRole('button', { name: 'Mark as done' }));
    expect((await screen.findByRole('alert')).textContent).toBe('This step closes by itself when PAI has what it needs.');
  });

  it('every word the requests screen needs exists in copy.json', () => {
    const w = copy.connect.requests as Record<string, unknown>;
    for (const k of ['use', 'kinds', 'levels', 'asOf', 'pending', 'gone', 'unavailable', 'failed']) expect(w[k]).toBeTruthy();
    expect(Object.keys(w.kinds as object).sort()).toEqual(['document', 'said', 'vault']);
    expect(Object.keys(w.levels as object).sort()).toEqual(['confirmed', 'shown', 'stated']);
  });
});
