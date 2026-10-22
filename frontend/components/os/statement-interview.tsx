'use client';

import { useState } from 'react';
import { progressLabel, type OsInterviewItem } from '@/lib/os-statements';

interface StatementInterviewProps {
  items: OsInterviewItem[];
  /** Called when the student leaves a card; the page saves it. */
  onSave: (id: string, answer: string) => void;
  busy?: boolean;
}

/** The interview (Slice 5 spec §5): one question per card with its hint, saved as the student goes, a progress
 * count, and the reviewer's follow-up questions on top. Mobile-first (360 px). */
export function StatementInterview({ items, onSave, busy = false }: StatementInterviewProps) {
  const ordered = [...items.filter((i) => i.follow_up), ...items.filter((i) => !i.follow_up)];
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-3">
      <p className="text-sm text-muted-foreground">{progressLabel(items)}</p>
      {ordered.map((item) => <QuestionCard key={item.id} item={item} onSave={onSave} busy={busy} />)}
    </div>
  );
}

function QuestionCard({ item, onSave, busy }: { item: OsInterviewItem; onSave: (id: string, a: string) => void; busy: boolean }) {
  const [text, setText] = useState(item.answer);
  const id = `q-${item.id}`;
  return (
    <section data-question={item.id}
             className={`flex flex-col gap-2 rounded-lg border p-3 ${item.follow_up ? 'border-primary bg-primary/5' : 'bg-card'}`}>
      {item.follow_up && <p className="text-xs font-medium text-primary">A new question about your draft</p>}
      <label htmlFor={id} className="break-words text-sm font-medium">
        {item.prompt}{!item.required && <span className="font-normal text-muted-foreground"> (optional)</span>}
      </label>
      {item.hint && <p className="break-words text-xs text-muted-foreground">{item.hint}</p>}
      <textarea id={id} rows={4} maxLength={4000} value={text} disabled={busy}
                className="w-full rounded-md border bg-background p-2 text-sm"
                onChange={(e) => setText(e.target.value)}
                onBlur={() => { if (text !== item.answer) onSave(item.id, text); }} />
    </section>
  );
}
