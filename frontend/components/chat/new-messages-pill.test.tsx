// @vitest-environment jsdom
/** Audit #13: "New messages" appears only when a reply really arrived below
 * while the student was reading history; scrolled up with nothing new, the
 * pill says "Back to latest". */
import { afterEach, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChatMessages } from './chat-messages';
import { I18nProvider } from '@/lib/i18n';
import type { WorkspaceMessage } from '@/lib/types';

vi.mock('./chat-message', () => ({ ChatMessage: ({ message }: { message: WorkspaceMessage }) => <p>{message.content}</p> }));
afterEach(cleanup);

const message = (id: string, messageType = 'chat'): WorkspaceMessage => ({
  messageId: id, sessionId: 'pai-counselor', senderType: 'agent', senderName: 'pai', messageType,
  content: `message ${id}`, metadata: {}, createdAt: new Date().toISOString(),
} as unknown as WorkspaceMessage);

function scrolledUp(container: HTMLElement) {
  Object.defineProperty(container, 'scrollHeight', { configurable: true, value: 2000 });
  Object.defineProperty(container, 'clientHeight', { configurable: true, value: 400 });
  container.scrollTop = 200;
  fireEvent.scroll(container);
}

it('audit #13: scrolled up with nothing new is not "New messages"; a new reply is', async () => {
  const view = (messages: WorkspaceMessage[]) => <I18nProvider><ChatMessages messages={messages} showAllSteps={false} /></I18nProvider>;
  const { container, rerender } = render(view([message('a'), message('b')]));
  const scroller = container.querySelector('.overflow-y-auto') as HTMLElement;
  await act(async () => { scrolledUp(scroller); });
  expect(screen.queryByRole('button', { name: 'New messages' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Back to latest' })).toBeTruthy();
  // A step line ("thinking") is not a message to read.
  rerender(view([message('a'), message('b'), message('t', 'thinking')]));
  expect(screen.queryByRole('button', { name: 'New messages' })).toBeNull();
  rerender(view([message('a'), message('b'), message('t', 'thinking'), message('c')]));
  expect(screen.getByRole('button', { name: 'New messages' })).toBeTruthy();
});
