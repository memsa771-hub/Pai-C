// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ChatMessage, splitNextStep } from './chat-message';
import { I18nProvider } from '@/lib/i18n';
import type { WorkspaceMessage } from '@/lib/types';

vi.mock('@/lib/api', () => ({ workspaceApi: { getFileUrl: vi.fn(), getDocumentStage: vi.fn() } }));
vi.mock('@/lib/workspace-context', () => ({ useWorkspace: () => ({ currentUser: { id: 'student', name: 'Sam' }, setSelectedFileId: vi.fn() }) }));
vi.mock('@/components/layout/layout-context', () => ({ useLayout: () => ({ setViewMode: vi.fn() }) }));
afterEach(cleanup);

const reply = (content: string, metadata: Record<string, unknown> = {}, senderType = 'agent') => ({
  messageId: 'm', sessionId: 'pai-counselor', senderType, senderName: 'pai', messageType: 'chat',
  content, metadata, createdAt: '2026-10-29T09:00:00Z',
}) as unknown as WorkspaceMessage;
const show = (message: WorkspaceMessage) => render(<I18nProvider><ChatMessage message={message} /></I18nProvider>);

it('sets the reply\'s last line, the next step, apart from the body', () => {
  show(reply('Engineering and computing both use maths.\n\nWhich subject do you enjoy most?'));
  const step = screen.getByTestId('next-step');
  expect(step.textContent).toBe('Which subject do you enjoy most?');
  expect(step.className).toContain('text-muted-foreground');
  expect(screen.getByText('Engineering and computing both use maths.').closest('[data-testid="next-step"]')).toBeNull();
});

it('leaves one-paragraph replies, list endings and the student\'s own words as they are', () => {
  expect(splitNextStep('Just one line.')).toEqual(['Just one line.', null]);
  expect(splitNextStep('Options:\n\n- one\n- two')[1]).toBeNull();
  expect(splitNextStep('Steps:\n\n1. Apply')[1]).toBeNull();
  expect(splitNextStep('Body.\n\nNext line.\n')).toEqual(['Body.', 'Next line.']);
  show(reply('I like maths.\n\nAnd physics.', {}, 'human'));
  expect(screen.queryByTestId('next-step')).toBeNull();
});

it('shows an about-PAI answer as a normal reply with the place it points to', () => {
  show(reply('Your Vault keeps everything you tell PAI, with where it came from.\n\nOpen your profile to check it.',
    { workspace_place: 'profile' }));
  expect(screen.getByText('Your Vault keeps everything you tell PAI, with where it came from.')).toBeTruthy();
  expect(screen.getByTestId('next-step').textContent).toBe('Open your profile to check it.');
  expect(screen.getByRole('button', { name: 'Your profile' })).toBeTruthy();
});
