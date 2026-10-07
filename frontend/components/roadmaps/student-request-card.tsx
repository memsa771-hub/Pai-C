'use client';

import { useRef, useState } from 'react';
import { workspaceApi } from '@/lib/api';
import { useT } from '@/lib/i18n';
import type { StudentRequest } from '@/lib/roadmaps';
import { useWorkspace } from '@/lib/workspace-context';
import { PAI_PRIMARY_CONVERSATION_ID } from '@/lib/primary-conversation';

export function StudentRequestCard({ request, onSent }: {
  request: StudentRequest;
  onSent?: () => void;
}) {
  const t = useT();
  const { currentUser } = useWorkspace();
  const input = useRef<HTMLInputElement>(null);
  const [answer, setAnswer] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if ((!answer.trim() && !file) || busy || !currentUser.id) return;
    setBusy(true); setError('');
    try {
      const uploaded = file ? await workspaceApi.uploadFile(file, PAI_PRIMARY_CONVERSATION_ID) : null;
      await workspaceApi.sendMessage(PAI_PRIMARY_CONVERSATION_ID,
        answer.trim() || uploaded?.filename || '', currentUser.name, undefined,
        uploaded ? [{ fileId: uploaded.id, filename: uploaded.filename,
                      contentType: uploaded.contentType, url: workspaceApi.getFileUrl(uploaded.id) }] : undefined,
        currentUser.id);
      setSent(true); setAnswer(''); setFile(null); onSent?.();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };

  return <section className="rounded-xl border border-amber-300 bg-amber-50/50 p-4 dark:bg-amber-950/10" aria-labelledby={`request-${request.id}`}>
    <h3 id={`request-${request.id}`} className="font-semibold">{t('counselorRoadmaps.requestTitle')}</h3>
    <p className="mt-1 text-sm">{request.reason}</p>
    <p className="mt-1 text-xs text-muted-foreground">{t('counselorRoadmaps.requestHint')}</p>
    {sent ? <p role="status" className="mt-3 text-sm">{t('counselorRoadmaps.requestSent')}</p>
      : <form onSubmit={(event) => void submit(event)} className="mt-3 space-y-2">
        <label htmlFor={`answer-${request.id}`} className="block text-sm font-medium">{t('counselorRoadmaps.requestAnswer')}</label>
        <textarea id={`answer-${request.id}`} value={answer} onChange={(event) => setAnswer(event.target.value)}
          rows={2} className="w-full rounded-lg border bg-background px-3 py-2 text-sm" />
        {request.accepts_upload && <>
          <input ref={input} type="file" className="sr-only" aria-label={t('counselorRoadmaps.requestUpload')}
            onChange={(event) => setFile(event.target.files?.[0] || null)} />
          <button type="button" onClick={() => input.current?.click()} className="rounded-lg border px-3 py-1.5 text-xs">
            {file?.name || t('counselorRoadmaps.requestUpload')}
          </button>
        </>}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div><button type="submit" disabled={busy || (!answer.trim() && !file)}
          className="rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground disabled:opacity-50">
          {busy ? t('counselorRoadmaps.requestSending') : t('counselorRoadmaps.requestSend')}
        </button></div>
      </form>}
  </section>;
}
