'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { rulesLabel, type OsProgrammeRules, type OsStatement } from '@/lib/os-statements';

interface StatementProgrammesProps {
  programmes: OsProgrammeRules[];
  statements: OsStatement[];
  /** Starts the programme's own statement. */
  onDraft: (programmeRef: string) => void;
  onPaste: (programmeRef: string, rules: { prompt: string | null; limit_words: number | null }) => void;
  disabled?: boolean;
}

/** Each programme in the plan (Slice 5 spec S5-D2): whether it asks for its own statement, a button to write it,
 * and, when the programme's pages say what we could not find, a place to paste its question and limit. */
export function StatementProgrammes({ programmes, statements, onDraft, onPaste, disabled = false }: StatementProgrammesProps) {
  if (programmes.length === 0) return null;
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-3">
      <p className="text-sm font-medium">Your programmes</p>
      {programmes.map((p) => (
        <ProgrammeRow key={p.programme_ref} rules={p} disabled={disabled} onDraft={onDraft} onPaste={onPaste}
                      started={statements.some((s) => s.kind === 'sop' && s.programme_ref === p.programme_ref)} />
      ))}
    </div>
  );
}

function ProgrammeRow({ rules, started, disabled, onDraft, onPaste }: {
  rules: OsProgrammeRules; started: boolean; disabled: boolean;
  onDraft: (ref: string) => void;
  onPaste: (ref: string, r: { prompt: string | null; limit_words: number | null }) => void;
}) {
  const [prompt, setPrompt] = useState(rules.source === 'student' ? rules.prompt ?? '' : '');
  const [limit, setLimit] = useState(rules.source === 'student' && rules.limit_words ? String(rules.limit_words) : '');
  return (
    <section data-programme={rules.programme_ref} className="flex flex-col gap-1 border-t pt-2 first:border-t-0 first:pt-0">
      <p className="break-words text-sm font-medium">{rules.programme_ref}</p>
      <p className="break-words text-xs text-muted-foreground">{rulesLabel(rules)}</p>
      {rules.prompt && rules.needed && <p className="break-words text-xs">Its question: {rules.prompt}</p>}
      {rules.needed && !started && (
        <Button size="sm" className="self-start" disabled={disabled} onClick={() => onDraft(rules.programme_ref)}>
          Write the statement for this programme
        </Button>
      )}
      {rules.source !== 'research' && (
        <details className="text-xs">
          <summary className="cursor-pointer">Does this programme ask for its own statement? Paste its question</summary>
          <div className="mt-2 flex flex-col gap-2">
            <textarea aria-label="The programme's question" rows={3} maxLength={4000} value={prompt}
                      className="w-full rounded-md border bg-background p-2 text-sm" onChange={(e) => setPrompt(e.target.value)} />
            <label className="flex flex-wrap items-center gap-2">
              Word limit
              <input type="number" min={1} inputMode="numeric" value={limit}
                     className="w-24 rounded-md border bg-background p-1 text-sm" onChange={(e) => setLimit(e.target.value)} />
            </label>
            <Button size="sm" variant="outline" className="self-start" disabled={disabled || (!prompt.trim() && !limit)}
                    onClick={() => onPaste(rules.programme_ref, { prompt: prompt.trim() || null,
                                                                   limit_words: limit ? Number(limit) : null })}>
              Save
            </Button>
          </div>
        </details>
      )}
    </section>
  );
}
