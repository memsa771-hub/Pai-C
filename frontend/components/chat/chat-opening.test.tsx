// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ChatView } from './chat-view';
import { I18nProvider } from '@/lib/i18n';

const state = vi.hoisted(() => ({ messages: [] as any[] }));
vi.mock('@/lib/workspace-context', () => ({ useWorkspace: () => ({
  agents: [], currentUser: { id: 'student', name: 'Student' },
  currentSessionId: 'pai-counselor', sessions: [], activeSessionIds: new Set(),
  stoppingSessionIds: new Set(), consumeSkipFocus: () => true,
  updateLastMessage: vi.fn(), setSessionActive: vi.fn(),
}) }));
vi.mock('@/hooks/use-polling', () => ({ useMessagePolling: () => ({
  messages: state.messages, loading: false, generation: 0, forceRefresh: vi.fn(),
}) }));
vi.mock('@/hooks/use-composing-signal', () => ({ useComposingSignal: () => ({}) }));
vi.mock('@/components/layout/layout-context', () => ({ useLayout: () => ({}) }));
vi.mock('@/components/layout/pai-system-status', () => ({
  usePaiSystemStatus: () => ({ tone: 'ready' }), OPERATOR_DOT_CLASS: {},
}));
vi.mock('@/components/layout/app-header', () => ({ DetailHeader: () => null }));
vi.mock('./chat-input', () => ({ ChatInput: () => null }));
vi.mock('./thread-status-bar', () => ({ ThreadStatusBar: () => null }));
vi.mock('./counselor-voice-control', () => ({ useCounselorVoice: () => ({}), VoiceModeButton: () => null, VoiceStatus: () => null }));
vi.mock('./counselor-request-panel', () => ({ CounselorRequestPanel: () => null }));
vi.mock('./counselor-research-status', () => ({ CounselorResearchStatus: () => null }));
vi.mock('@/components/counselor/counselor-mirror-card', () => ({ CounselorMirrorCard: () => null }));
vi.mock('./share-dialog', () => ({ ShareDialog: () => null }));
vi.mock('./chat-messages', () => ({ ChatMessages: ({ messages }: any) => <div>{messages.map((m: any) => <p key={m.messageId}>{m.content}</p>)}</div> }));

afterEach(() => { cleanup(); state.messages = []; });
it('shows the existing typing state while empty, then the delivered opening', () => {
  const view = render(<I18nProvider><ChatView /></I18nProvider>);
  expect(screen.getByRole('status')).toBeTruthy();
  state.messages = [{ messageId: 'opening', sessionId: 'pai-counselor',
    senderType: 'agent', senderName: 'pai', messageType: 'chat',
    content: 'Welcome. Tell me about yourself.', metadata: {}, createdAt: new Date().toISOString() }];
  view.rerender(<I18nProvider><ChatView /></I18nProvider>);
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.getByText('Welcome. Tell me about yourself.')).toBeTruthy();
});
