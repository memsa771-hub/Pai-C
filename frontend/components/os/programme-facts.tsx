'use client';

import { ExternalLink } from 'lucide-react';
import { sourceHost } from '@/lib/os-inbox';
import {
  checkedLabel,
  fieldLabel,
  fillDraft,
  formatFactValue,
  statusLabel,
  type OsFact,
  type OsProgramme,
} from '@/lib/os-programmes';

/** The student's programme facts (Slice 2 spec §4.9): mobile-first (360 px), every value with its status and
 * source, the quote on tap, and an "Ask the university" draft for facts that are not checked. */
export function ProgrammeFacts({ programmes }: { programmes: OsProgramme[] }) {
  if (programmes.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted-foreground">No programmes in your plan yet.</p>;
  }
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-4">
      {programmes.map((p) => (
        <section key={`${p.ref}:${p.intake_year}`} id={p.ref} aria-label={p.name} className="rounded-lg border bg-card p-3">
          <h2 className="mb-2 break-words text-sm font-semibold">
            {p.university ? `${p.university} · ${p.name}` : p.name}
          </h2>
          {p.facts.length === 0 ? (
            <p className="text-xs text-muted-foreground">Nothing checked yet for this programme.</p>
          ) : (
            <dl className="flex flex-col gap-3">
              {p.facts.map((f) => (
                <FactRow key={f.field} programme={p} fact={f} />
              ))}
            </dl>
          )}
        </section>
      ))}
    </div>
  );
}

function FactRow({ programme, fact }: { programme: OsProgramme; fact: OsFact }) {
  const checked = fact.status === 'confirmed';
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium text-muted-foreground">{fieldLabel(fact.field)}</dt>
      <dd className="mt-0.5 min-w-0 break-words text-sm">
        <span>{formatFactValue(fact.value)}</span>
        <span className={`ml-2 rounded px-1.5 py-0.5 text-xs ${checked ? 'bg-muted' : 'bg-amber-100 text-amber-900'}`}>
          {statusLabel(fact.status)}
        </span>
        <p className="mt-1 text-xs text-muted-foreground">
          {checked && <span className="mr-2">{checkedLabel(fact.checked_at)}</span>}
          {fact.source_url && (
            <a href={fact.source_url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline">
              source: {sourceHost(fact.source_url)}
              <ExternalLink className="size-3" aria-hidden />
            </a>
          )}
        </p>
        {fact.conflict_note && <p className="mt-1 break-words text-xs text-amber-900">{fact.conflict_note}</p>}
        {fact.quote && (
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-muted-foreground">Show the quote</summary>
            <blockquote className="mt-1 break-words border-l-2 pl-2 italic">{fact.quote}</blockquote>
          </details>
        )}
        {!checked && (
          <details className="mt-1 text-xs">
            <summary className="cursor-pointer text-primary">Ask the university</summary>
            <p className="mt-1 text-muted-foreground">Copy this and send it from your own email.</p>
            <pre className="mt-1 whitespace-pre-wrap break-words rounded bg-muted p-2 font-sans">
              {fillDraft(programme.draft_email, programme, fact)}
            </pre>
          </details>
        )}
      </dd>
    </div>
  );
}
