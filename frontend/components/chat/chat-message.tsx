'use client';

import { ConversationCard, type InlineCard } from '@/components/counselor/workspace/inline-card';
import { FactCard, type OfferedFact } from '@/components/counselor/workspace/fact-card';
import { cn } from '@/lib/utils';
import { Possibilities, PathsFound } from '@/components/counselor/possibilities';
import { PlaceLink } from '@/components/counselor/place-link';
import { Button } from '@/components/ui/button';
import { Copy, Check, FileIcon, Download, Eye, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import {
  isDocumentAttachment,
  SETTLED_DOCUMENT_STAGES,
  type DocumentStage,
} from '@/lib/document-types';
import type { WorkspaceMessage, WorkspaceAgent } from '@/lib/types';
import { AgentAvatar } from '@/components/agents/agent-avatar';
import { MarkdownContent } from './markdown-content';
import { workspaceApi } from '@/lib/api';
import { useLayout } from '@/components/layout/layout-context';
import { useWorkspace } from '@/lib/workspace-context';
import { useFormatters, useT } from '@/lib/i18n';
import { agentLabel } from '@/lib/helpers';
import { RoadmapComparison } from './roadmap-comparison';
import type { Roadmap } from '@/lib/roadmaps';

interface Attachment {
  fileId: string;
  filename: string;
  contentType: string;
  url: string;
}

function isPreviewable(contentType: string, filename: string): boolean {
  if (contentType?.startsWith('image/')) return true;
  if (contentType === 'text/html' || /\.html?$/i.test(filename)) return true;
  if (contentType === 'text/markdown' || /\.mdx?$/i.test(filename)) return true;
  if (contentType?.startsWith('text/') || /\.(json|js|ts|tsx|jsx|py|rs|go|java|rb|sh|yaml|yml)$/i.test(filename)) return true;
  return false;
}

/** Poll every few seconds; stop once the stage settles or after ~5 minutes. */
const STAGE_POLL_MS = 3000;
const STAGE_POLL_MAX = 100;

/**
 * Live processing stage under a PDF/DOCX attachment.
 *
 * Reads the server's stage rather than local state, so a student who leaves
 * the chat and comes back mid-processing sees where the document really is —
 * previously the file just sat there looking idle for the ~30s extraction.
 */
function DocumentStatus({ fileId }: { fileId: string }) {
  const t = useT();
  const [stage, setStage] = useState<DocumentStage | null>(null);

  useEffect(() => {
    let cancelled = false;
    let polls = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await workspaceApi.getDocumentStage(fileId);
        if (cancelled) return;
        setStage(next);
        if (SETTLED_DOCUMENT_STAGES.includes(next)) return;
      } catch {
        // Transient: keep the last known stage and try again.
      }
      polls += 1;
      if (!cancelled && polls < STAGE_POLL_MAX) timer = setTimeout(poll, STAGE_POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [fileId]);

  if (stage === null || stage === 'unsupported') return null;

  const inProgress = stage === 'reading' || stage === 'understanding';
  const label = stage === 'reading'
    ? t('chat.documentReading')
    : stage === 'understanding'
      ? t('chat.documentUnderstanding')
      : stage === 'done'
        ? t('chat.documentDone')
        : t('chat.documentFailed');

  return (
    <div
      className={cn(
        'mt-1 flex items-center gap-1.5 text-2xs',
        stage === 'failed' ? 'text-destructive' : 'text-muted-foreground',
      )}
      role="status"
      aria-live="polite"
    >
      {inProgress && <Loader2 className="size-3 animate-spin" aria-hidden="true" />}
      {stage === 'done' && <Check className="size-3 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />}
      <span>{label}</span>
    </div>
  );
}

function Attachments({ items }: { items: Attachment[] }) {
  if (!items || items.length === 0) return null;

  const { setViewMode } = useLayout();
  const { setSelectedFileId } = useWorkspace();

  const openPreview = useCallback((fileId: string) => {
    setSelectedFileId(fileId);
    setViewMode('files');
  }, [setSelectedFileId, setViewMode]);

  // Regenerate URLs from fileId to ensure they include current auth token
  const fixedItems = useMemo(() =>
    items.map((a) => ({ ...a, url: workspaceApi.getFileUrl(a.fileId) })),
    [items]
  );

  const images = fixedItems.filter((a) => a.contentType?.startsWith('image/'));
  const files = fixedItems.filter((a) => !a.contentType?.startsWith('image/'));

  return (
    <div className="mt-2 space-y-2">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((img) => (
            <button
              key={img.fileId}
              type="button"
              onClick={() => openPreview(img.fileId)}
              className="block rounded-lg overflow-hidden border hover:shadow-md transition-shadow max-w-sm cursor-pointer text-left"
            >
              <img
                src={img.url}
                alt={img.filename}
                className="max-h-64 w-auto object-contain"
                loading="lazy"
              />
            </button>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((file) => {
            const previewable = isPreviewable(file.contentType, file.filename);
            const chip = previewable ? (
              <button
                type="button"
                onClick={() => openPreview(file.fileId)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg border bg-muted hover:bg-muted/80 transition-colors text-sm cursor-pointer"
              >
                <Eye className="size-4 text-muted-foreground shrink-0" />
                <span className="truncate max-w-[200px]">{file.filename}</span>
              </button>
            ) : (
              <a
                href={file.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-3 py-2 rounded-lg border bg-muted hover:bg-muted/80 transition-colors text-sm"
              >
                <FileIcon className="size-4 text-muted-foreground shrink-0" />
                <span className="truncate max-w-[200px]">{file.filename}</span>
                <Download className="size-3 text-muted-foreground shrink-0" />
              </a>
            );
            return (
              <div key={file.fileId} className="flex flex-col">
                {chip}
                {isDocumentAttachment(file.filename, file.contentType) && (
                  <DocumentStatus fileId={file.fileId} />
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface ChatMessageProps {
  message: WorkspaceMessage;
  agents?: WorkspaceAgent[];

}

export const ChatMessage = memo(function ChatMessage({ message, agents = [] }: ChatMessageProps) {
  const { currentUser } = useWorkspace();
  const t = useT();
  const { formatTime } = useFormatters();
  const isHuman = message.senderType === 'human' || message.senderType === 'user';
  const isSystem = message.messageType === 'status';
  const [copied, setCopied] = useState(false);

  const agentNames = useMemo(() => agents.map((a) => a.agentName), [agents]);
  const agentLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const a of agents) {
      if (a.displayName) labels[a.agentName] = agentLabel(a);
    }
    return labels;
  }, [agents]);
  const agent = agents.find((a) => a.agentName === message.senderName);
  const rawAttachments = (message.metadata?.attachments as Record<string, unknown>[]) || [];
  const attachments: Attachment[] = rawAttachments.map((a) => ({
    fileId: (a.fileId || a.file_id || '') as string,
    filename: (a.filename || '') as string,
    contentType: (a.contentType || a.content_type || '') as string,
    url: '',
  }));

  const timestamp = message.createdAt ? formatTime(message.createdAt) : null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t('chat.copyFailed'));
    }
  };

  // Status messages — subtle inline
  if (isSystem) {
    const isQueued = message.content.includes('queued');
    return (
      <div className="flex justify-center py-1">
        <span className={cn(
          'text-xs italic',
          isQueued
            ? 'text-foreground/80'
            : 'text-muted-foreground'
        )}>
          {agent ? agentLabel(agent) : message.senderName}: {message.content}
        </span>
      </div>
    );
  }

  // ── Human message ──
  // The workspace has exactly one human (its owner), so this is always "your"
  // turn: a right-aligned brand bubble. The name is for screen readers only,
  // so the student never sees their own name repeated on every line.
  if (isHuman) {
    const isCurrentUser = !!message.senderId && message.senderId === currentUser.id;
    const displayName = isCurrentUser
      ? t('chat.you')
      : (message.senderName && message.senderName !== 'user' ? message.senderName : t('chat.you'));

    return (
      <div className="mx-auto w-full max-w-[46rem] py-3">
        <div className="flex flex-col items-end">
          <span className="sr-only">{displayName}:</span>
          <div className="max-w-[85%] rounded-[22px] rounded-br-md bg-brand-soft px-4 py-2.5 text-left text-[15px] leading-relaxed text-foreground sm:max-w-[75%] [&_a]:underline">
            <ConversationCard card={message.metadata?.counselor_card as InlineCard | undefined} channel={message.sessionId}><MarkdownContent content={message.content} agentNames={agentNames} agentLabels={agentLabels} /></ConversationCard>
          </div>
          {/* Attachments and their status sit below the bubble, on the page
              surface, so chips and status text keep normal contrast. */}
          <div className="flex max-w-[85%] justify-end sm:max-w-[75%]"><Attachments items={attachments} /></div>
          {!!message.metadata?.fact_card && <div className="w-full max-w-lg"><FactCard card={message.metadata.fact_card as OfferedFact}/></div>}
          {timestamp && <span className="mt-1 px-1 text-[11px] text-muted-foreground">{timestamp}</span>}
        </div>
      </div>
    );
  }

  // ── Agent message ──
  // PAI speaks on the page, not in a bubble: its name above, then the reply at
  // full reading width, like a letter. Rich cards (fact, rating, paths,
  // roadmaps) follow the text.
  return (
    <div className="group mx-auto w-full max-w-[46rem] py-3">
      <div className="min-w-0">
        <div className="mb-1.5 flex items-center gap-2">
          <AgentAvatar name={message.senderName} size={26} />
          <span className="text-sm font-bold">{agent ? agentLabel(agent) : message.senderName}</span>
        </div>
        <div className="min-w-0">
          <div className="max-w-full text-[15.5px] leading-7 text-foreground [&_p+p]:mt-3">
            <ConversationCard card={message.metadata?.counselor_card as InlineCard | undefined} channel={message.sessionId}><MarkdownContent content={message.content} agentNames={agentNames} agentLabels={agentLabels} /></ConversationCard>
            <Attachments items={attachments} />
          </div>
          {!!message.metadata?.fact_card && <FactCard card={message.metadata.fact_card as OfferedFact}/>}
          {Array.isArray(message.metadata?.roadmaps) && <RoadmapComparison initial={message.metadata.roadmaps as unknown as Roadmap[]} />}
          {typeof message.metadata?.possibility_id === 'string' && <Possibilities id={message.metadata.possibility_id} />}
          {Array.isArray(message.metadata?.paths_found) && <PathsFound ids={message.metadata.paths_found as string[]} />}
          {typeof message.metadata?.workspace_place === 'string' && <PlaceLink place={message.metadata.workspace_place} />}

          <div className="mt-1 flex min-h-8 items-center gap-2 px-1">
            {timestamp && <span className="text-[11px] text-muted-foreground">{timestamp}</span>}
            {/* Copy is revealed on hover or focus, and always on touch screens. */}
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1 px-2 text-xs text-muted-foreground opacity-100 transition-opacity hover:text-foreground sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
              onClick={handleCopy}
              aria-label={t('chat.copyMessage')}
            >
              {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
              {copied ? t('common.copied') : t('common.copy')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
});
