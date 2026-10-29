'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  APPROVED_COPY,
  NOT_FOUND_COPY,
  countLabel,
  kindLabel,
  overBy,
  segments,
  shortHash,
  wordCount,
  type OsStatement,
} from '@/lib/os-statements';

interface StatementEditorProps {
  statement: OsStatement;
  /** Programme ref -> name: a programme statement is named by its programme. */
  names?: Record<string, string>;
  onSave: (text: string) => void;
  onRewrite: () => void;
  onApprove: (version: number) => void;
  busy?: boolean;
}

/** One draft (Slice 5 spec §5): the text in an editor with its count and limit, the phrases we could not find in
 * the student's material highlighted, the reviewer's notes, and Save / Write again / Approve this version. */
export function StatementEditor({ statement, names = {}, onSave, onRewrite, onApprove, busy = false }: StatementEditorProps) {
  const v = statement.version;
  const [text, setText] = useState(v?.text ?? '');
  if (!v) return <p className="text-sm text-muted-foreground">No draft yet.</p>;
  const words = wordCount(text);
  const over = overBy(words, v.limit_words);
  const edited = text !== v.text;
  const approved = statement.approval?.version === v.number && !edited ? statement.approval : null;
  const fixes = v.critic?.fixes ?? [];
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-3">
      <h2 className="break-words text-base font-semibold">{kindLabel(statement.kind, statement.programme_ref, names)}</h2>
      <textarea aria-label="Your text" rows={14} value={text} disabled={busy}
                className="w-full rounded-md border bg-background p-2 text-sm" onChange={(e) => setText(e.target.value)} />
      <p className={`text-xs ${over ? 'text-destructive' : 'text-muted-foreground'}`}>
        {countLabel(words, v.limit_words)}{over && ` · ${over}`}
      </p>
      {v.flags.length > 0 && !edited && (
        <div className="rounded-lg border border-amber-500/50 bg-amber-500/5 p-3">
          <p className="mb-2 text-xs font-medium">{NOT_FOUND_COPY}:</p>
          <p className="whitespace-pre-wrap break-words text-sm">
            {segments(v.text, v.flags).map((s, i) => s.flagged
              ? <mark key={i} title={NOT_FOUND_COPY} className="rounded bg-amber-200 px-0.5 dark:bg-amber-700">{s.text}</mark>
              : <span key={i}>{s.text}</span>)}
          </p>
        </div>
      )}
      {fixes.length > 0 && (
        <div className="rounded-lg border bg-card p-3">
          <p className="mb-1 text-xs font-medium">Notes from the reviewer</p>
          <ul className="list-disc pl-5 text-sm">
            {fixes.map((f, i) => <li key={i} className="break-words">{f}</li>)}
          </ul>
        </div>
      )}
      {approved ? (
        <div className="rounded-lg border border-green-600/50 bg-green-600/5 p-3 text-sm">
          <p className="font-medium">Approved: version {approved.version}, {new Date(approved.approved_at).toLocaleDateString()}</p>
          <p className="break-words text-xs text-muted-foreground">Fingerprint {shortHash(approved.sha256)}</p>
          <p className="mt-1 text-xs">{APPROVED_COPY}.</p>
        </div>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy || !edited || !text.trim()} onClick={() => onSave(text)}>Save</Button>
        <Button variant="outline" disabled={busy} onClick={onRewrite}>Write again</Button>
        <Button variant="secondary" disabled={busy || edited || approved !== null} onClick={() => onApprove(v.number)}>
          Approve this version
        </Button>
      </div>
    </div>
  );
}
