'use client';

import { useEffect, useRef, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  GROUP_TITLES,
  KIND_LABELS,
  actionHint,
  changeLine,
  completeActions,
  programmeName,
  type CompleteAction,
  dateLabels,
  dueNote,
  formatDue,
  groupItems,
  isWaiting,
  sourceHost,
  waitingText,
  type OsInboxItem,
  reviewPage,
  collapseNotices,
} from '@/lib/os-inbox';
import { statusLabel, type FactStatus } from '@/lib/os-programmes';
import { factLevel, stepLevel, weakerLevel } from '@/lib/os-my-plan';
import { FactSource } from './fact-source';
import { isNumeric, sourceParts, typedValue, type OsRequest, type RequestWords } from '@/lib/os-requests';
import copy from '@/components/counselor/workspace/copy.json';
import { useMyPlan } from './my-plan-context';
import { checkLabel, chipLabel, chipTone, lineText, type OsNote } from '@/lib/os-self-serve';

interface InboxListProps {
  items: OsInboxItem[];
  now: Date;
  onComplete: (item: OsInboxItem, payload?: Record<string, unknown>) => void;
  busyId?: number | null;
  /** Programme ref -> the status of its date facts (Slice 2): shown next to provisional/estimated. */
  factStatus?: Record<string, FactStatus | null>;
  /** The programme facts page; items of a programme link to its section there. */
  programmesHref?: string;
  /** The workspace's base path (`/<workspace>`): a review step links to its pack or visa file there. */
  basePath?: string;
  /** Slice 4: eligibility changes, with up to 3 suggested swaps each. */
  notes?: OsNote[];
  /** Programme ref -> its name, for notes and suggestions. */
  names?: Record<string, string>;
  /** The page asks the student first (swapPrompt), then swaps. */
  onSwap?: (note: OsNote, inRef: string) => void;
  onReadNote?: (note: OsNote) => void;
  /** P1-T8: the student's answer to a "which is right" request: a choice id, and a typed value for `new`. */
  onAnswer?: (request: OsRequest, choice: string, value?: string | number) => void;
}

const words = copy.connect.requests as RequestWords;

/** The two values of a "which is right" request as buttons, each with where it is held, and a field for the right
 * value when the API allows it (P1-T8, R-21). Sentences come from the API; the few words it does not send, from copy.json. */
function WhichIsRight({ request, busy, onAnswer }: { request: OsRequest; busy: boolean; onAnswer?: InboxListProps['onAnswer'] }) {
  const [typed, setTyped] = useState('');
  const id = `new-${request.id}`;
  const numeric = isNumeric(request);
  const value = typedValue(typed, numeric);
  return (
    <div className="mt-2 flex flex-col gap-2">
      {request.choices.map((c) => (
        <Button key={c.choice} type="button" variant="outline" disabled={busy || !onAnswer}
                className="h-auto w-full flex-col items-start gap-0.5 whitespace-normal break-words py-2 text-left"
                onClick={() => onAnswer?.(request, c.choice, undefined)}>
          <span className="text-sm font-semibold">{String(c.value)}</span>
          <span className="text-xs font-normal">{c.label}</span>
          <span className="text-xs font-normal text-muted-foreground">{sourceParts(c, words).join(' · ')}</span>
        </Button>
      ))}
      {request.allow_new && (
        <form className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => { e.preventDefault(); if (value !== null) onAnswer?.(request, 'new', value); }}>
          <label htmlFor={id} className="w-full text-xs text-muted-foreground">{request.new_label}</label>
          <input id={id} value={typed} onChange={(e) => setTyped(e.target.value)} inputMode={numeric ? "decimal" : "text"} disabled={busy}
                 className="h-9 min-w-0 flex-1 rounded-md border bg-background px-2 text-sm" />
          <Button type="submit" size="sm" disabled={busy || !onAnswer || value === null}>{words.use}</Button>
        </form>
      )}
    </div>
  );
}

function NoteCard({ note, names, onSwap, onReadNote }: { note: OsNote; names: Record<string, string>;
  onSwap?: InboxListProps['onSwap']; onReadNote?: InboxListProps['onReadNote'] }) {
  const name = names[note.programme_ref] ?? note.programme_ref;
  const reasons = note.payload.lines.filter((l) => l.status !== 'likely_meets');
  return (
    <li className="rounded-2xl border bg-card p-4 shadow-card text-sm">
      <p className="flex flex-wrap items-center gap-2 font-medium">
        <span className="min-w-0 break-words">{name}</span>
        <span className={`rounded px-1.5 py-0.5 text-xs ${chipTone(note.verdict)}`}>{chipLabel(note.verdict)}</span>
      </p>
      <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
        {reasons.map((l) => (
          <li key={l.check} className="break-words">{checkLabel(l.check)}: {lineText(l)}</li>
        ))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-2">
        {onSwap && note.payload.plan_id !== undefined && note.payload.suggestions.map((ref) => (
          <Button key={ref} size="sm" variant="outline" onClick={() => onSwap(note, ref)}>
            Swap for {names[ref] ?? ref}
          </Button>
        ))}
        {onReadNote && <Button size="sm" variant="ghost" onClick={() => onReadNote(note)}>OK</Button>}
      </div>
    </li>
  );
}

/** The PAI OS student inbox (Slice 1 spec §4.11): mobile-first, one action per item. */
export function InboxList({ items, now, onComplete, busyId = null, factStatus = {}, programmesHref, basePath, notes = [],
                            names = {}, onSwap, onReadNote, onAnswer }: InboxListProps) {
  // an answer that asks first (Slice 9 Task 11): "Not admitted" names the programme and waits for a second tap
  const [asking, setAsking] = useState<{ id: number; action: CompleteAction } | null>(null);
  // focus (batch B review): into the question when it opens, back to the button that opened it on Cancel
  const [returnTo, setReturnTo] = useState<string | null>(null);
  const { on } = useMyPlan();
  const root = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (asking) {
      cancel.current?.focus();
    } else if (returnTo) {
      root.current?.querySelector<HTMLButtonElement>(`[data-ask="${returnTo}"]`)?.focus();
      setReturnTo(null);
    }
  }, [asking, returnTo]);
  const { items: shown, copies } = collapseNotices(items);
  const todo = shown.filter((i) => !isWaiting(i));
  const waiting = items.filter(isWaiting);  // blocked on a fact: listed to say what the plan waits for
  if (items.length === 0 && notes.length === 0) {
    return <p className="px-4 py-10 text-center text-sm text-muted-foreground">Nothing to do right now.</p>;
  }
  return (
    <div ref={root} className="flex flex-col gap-6">
      {notes.length > 0 && (
        <section aria-label="Eligibility updates">
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Eligibility updates
          </h2>
          <ul className="flex flex-col gap-2">
            {notes.map((n) => <NoteCard key={n.id} note={n} names={names} onSwap={onSwap} onReadNote={onReadNote} />)}
          </ul>
        </section>
      )}
      {groupItems(todo, now).map(({ group, items: groupItemsList }) => (
        <section key={group} aria-label={GROUP_TITLES[group]}>
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {GROUP_TITLES[group]}
          </h2>
          <ul className="flex flex-col gap-2">
            {groupItemsList.map((item) => {
              const due = formatDue(item);
              const fact = item.programme_ref ? factStatus[item.programme_ref] : null;
              const labels = on ? [] : [...dateLabels(item), ...(due && fact ? [statusLabel(fact)] : [])];
              const source = item.citations[0];
              const prog = programmeName(item, names);
              const hint = actionHint(item);
              const note = dueNote(item);
              return (
                <li key={item.id} className="rounded-2xl border bg-card p-4 shadow-card">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium leading-snug">
                        {item.inbox_kind && (
                          <span className="mr-1 text-muted-foreground">{KIND_LABELS[item.inbox_kind]} ·</span>
                        )}
                        {item.title}
                      </p>
                      {prog && <p className="mt-0.5 break-words text-sm font-semibold">{prog}</p>}
                      {(item.changes ?? []).length > 0 && (
                        <ul className="mt-1 flex flex-col gap-0.5 text-xs">
                          {(item.changes ?? []).map((c) => (
                            <li key={`${c.change}:${c.instance_key}`} className="break-words">{changeLine(c, names)}</li>
                          ))}
                        </ul>
                      )}
                      {hint && <p className="mt-1 break-words text-xs text-muted-foreground">{hint}</p>}
                      {item.request?.kind === 'which_is_right' && (
                        <WhichIsRight request={item.request} busy={busyId === item.id} onAnswer={onAnswer} />
                      )}
                      {(due || labels.length > 0) && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {due}
                          {labels.map((label) => (
                            <span key={label} className="ml-2 rounded bg-muted px-1.5 py-0.5">
                              {label}
                            </span>
                          ))}
                        </p>
                      )}
                      {note && <p className="mt-0.5 break-words text-xs text-muted-foreground">{note}</p>}
                      {on && (due || source) && (
                        <p className="mt-1">
                          <FactSource
                            level={due ? (fact ? weakerLevel(stepLevel(item), factLevel(fact)) : stepLevel(item)) : null}
                            url={source?.url}
                          />
                        </p>
                      )}
                      {!on && source && (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-xs text-primary underline-offset-2 hover:underline"
                        >
                          source: {sourceHost(source.url)}
                          <ExternalLink className="size-3" aria-hidden />
                        </a>
                      )}
                      {programmesHref && item.programme_ref && fact && (
                        <a
                          href={`${programmesHref}#${item.programme_ref}`}
                          className="mt-1 ml-3 inline-flex text-xs text-primary underline-offset-2 hover:underline"
                        >
                          programme facts
                        </a>
                      )}
                    </div>
                    {asking?.id !== item.id && (
                      <div className="flex shrink-0 flex-col gap-1">
                        {(() => {
                          const review = reviewPage(item);
                          return review && basePath ? (
                            <Button asChild size="sm" variant="outline">
                              <a href={`${basePath}/${review.page}`}>{review.label}</a>
                            </Button>
                          ) : null;
                        })()}
                        {completeActions(item, names).map((a) => (
                          <Button key={a.label} size="sm" variant="outline" disabled={busyId === item.id}
                                  data-ask={`${item.id}:${a.label}`}
                                  onClick={() => (a.confirm ? setAsking({ id: item.id, action: a })
                                    : [item.id, ...(copies.get(item.id) ?? [])].forEach((id) =>
                                        onComplete(id === item.id ? item : { ...item, id }, a.payload)))}>
                            {a.label}
                          </Button>
                        ))}
                      </div>
                    )}
                  </div>
                  {asking?.id === item.id && asking.action.confirm && (
                    <div role="alertdialog" aria-label={asking.action.label}
                         className="mt-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-950">
                      <p className="break-words">{asking.action.confirm.question}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Button size="sm" variant="destructive" disabled={busyId === item.id}
                                className="h-auto max-w-full whitespace-normal break-words py-1.5 text-left"
                                onClick={() => { const a = asking.action; setAsking(null); onComplete(item, a.payload); }}>
                          {asking.action.confirm.yes}
                        </Button>
                        <Button ref={cancel} size="sm" variant="outline"
                                onClick={() => { setReturnTo(`${item.id}:${asking.action.label}`); setAsking(null); }}>
                          Cancel
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      ))}
      {waiting.length > 0 && (
        <section aria-label="Waiting">
          <h2 className="mb-2 px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Waiting</h2>
          <ul className="flex flex-col gap-2">
            {waiting.map((item) => {
              const prog = programmeName(item, names);
              return (
                <li key={item.id} className="rounded-lg border border-dashed bg-card p-3">
                  <p className="text-sm font-medium leading-snug">{item.title}</p>
                  {prog && <p className="mt-0.5 break-words text-sm font-semibold">{prog}</p>}
                  <p className="mt-1 break-words text-xs text-muted-foreground">{waitingText(item)}</p>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
