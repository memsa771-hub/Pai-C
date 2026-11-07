'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  highlight, kindLabel, parseValue, resolutionLabel, showValue, stepsFor,
  type OsReviewDetail, type OsReviewer,
} from '@/lib/os-review';

export interface ReviewActions {
  review: (id: number, body: Record<string, unknown>) => Promise<void>;
  collect: (id: number, body: Record<string, unknown>) => Promise<void>;
  resolve: (id: number, outcome: 'resolved' | 'dismissed', note: string) => Promise<void>;
  upload: (id: number, file: File) => Promise<number>;
  openFile: (fileId: number) => void;
}

/** One review item (P2-T5, §4.5): the fact, the page with the quote marked, the files, and the actions for this reviewer. */
export function ReviewItem({ detail, reviewer, busy, actions }: {
  detail: OsReviewDetail; reviewer: OsReviewer; busy: boolean; actions: ReviewActions;
}) {
  const { item, fact, snapshot } = detail;
  const closed = item.status === 'closed';
  return (
    <article aria-label={`Review item ${item.id}`} className="rounded-2xl border bg-card p-4 shadow-card text-sm">
      <h2 className="break-words text-base font-semibold">{kindLabel(item.kind)}{item.field ? `: ${item.field}` : ''}</h2>
      {item.summary && <p className="mt-1 break-words">{item.summary}</p>}
      {item.join_count > 0 && <p className="text-xs text-muted-foreground">Reported again {item.join_count} time(s).</p>}
      {closed && <p role="status" className="mt-2 font-medium">Closed: {resolutionLabel(item.resolution)}</p>}
      {fact && <FactBlock detail={detail} />}
      {snapshot ? (
        <section aria-label="Page text" className="mt-3">
          <p className="text-xs text-muted-foreground">
            Page read {new Date(snapshot.fetched_at).toLocaleString()} ({snapshot.read_method}).{' '}
            {snapshot.quote_found ? 'The quote is on the page.' : 'The quote was NOT found on the page.'}
            {snapshot.truncated ? ' Text cut short.' : ''}
          </p>
          <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-background p-2 text-xs">
            {highlight(snapshot.text, fact?.quote ?? '').map((s, i) =>
              s.mark ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>)}
          </pre>
        </section>
      ) : fact ? <p className="mt-3 text-xs text-muted-foreground">No stored page text for this source.</p> : null}
      {detail.files.length > 0 && (
        <ul aria-label="Evidence files" className="mt-3 flex flex-col gap-1">
          {detail.files.map((f) => (
            <li key={f.id}>
              <button type="button" className="underline" onClick={() => actions.openFile(f.id)}>{f.filename}</button>
              <span className="text-xs text-muted-foreground"> · {f.content_type} · {f.size} bytes{f.uploaded_by ? ` · ${f.uploaded_by}` : ''}</span>
            </li>
          ))}
        </ul>
      )}
      {detail.reviews.length > 0 && (
        <ul aria-label="Reviews" className="mt-3 flex flex-col gap-1 text-xs">
          {detail.reviews.map((r) => (
            <li key={r.id} className="break-words">{r.reviewer} ({r.kind}) · {r.step}: {r.outcome}{r.note ? ` · ${r.note}` : ''}</li>
          ))}
        </ul>
      )}
      {!closed && detail.my_review && <p role="status" className="mt-3">You gave: {detail.my_review.step} {detail.my_review.outcome}.</p>}
      {!closed && !detail.my_review && item.kind === 'verify' && fact && (
        <VerifyForm detail={detail} reviewer={reviewer} busy={busy} actions={actions} />
      )}
      {!closed && item.kind === 'collect' && <CollectForm detail={detail} busy={busy} actions={actions} />}
      {!closed && item.kind !== 'verify' && item.kind !== 'collect' && <ResolveForm id={item.id} busy={busy} actions={actions} />}
    </article>
  );
}

function FactBlock({ detail }: { detail: OsReviewDetail }) {
  const f = detail.fact!;
  return (
    <section aria-label="Fact" className="mt-3 rounded-md border bg-background p-2">
      <p className="break-words font-mono text-xs">{showValue(f.value)}</p>
      <p className="mt-1 break-words text-xs">Quote: “{f.quote}”</p>
      <p className="break-words text-xs">Source: <a className="underline" href={f.url} target="_blank" rel="noreferrer noopener">{f.url}</a></p>
      <p className="mt-1 text-xs text-muted-foreground">
        {f.status}{f.high_stakes ? ' · high-stakes' : ''} · {f.fact_class} · intake {f.intake_term ? `${f.intake_term} ` : ''}{f.intake_year}
        {f.owner_ref ? ` · owner ${f.owner_ref}` : ''}{f.read_method ? ` · read by ${f.read_method}` : ''}
        {f.language ? ` · ${f.language}` : ''}
      </p>
    </section>
  );
}

function VerifyForm({ detail, reviewer, busy, actions }: {
  detail: OsReviewDetail; reviewer: OsReviewer; busy: boolean; actions: ReviewActions;
}) {
  const steps = stepsFor(reviewer.role);
  const [step, setStep] = useState<'check' | 'approve'>(steps[0]);
  const [note, setNote] = useState('');
  const [value, setValue] = useState('');
  const [quote, setQuote] = useState('');
  const [fileId, setFileId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = detail.item.id;
  const send = (outcome: string, extra: Record<string, unknown> = {}) => {
    setError(null);
    void actions.review(id, { step, outcome, note: note.trim() || null, evidence_file_id: fileId, ...extra });
  };
  const correct = () => {
    const parsed = parseValue(value);
    if (!parsed.ok) return setError('The corrected value must be valid JSON.');
    if (!quote.trim()) return setError('A correction needs its quote from the page.');
    send('wrong', { corrected_value: parsed.value, corrected_quote: quote.trim() });
  };
  const needNote = (outcome: string) => (note.trim() ? send(outcome) : setError('Say what is wrong or unclear in the note.'));
  return (
    <form className="mt-4 flex flex-col gap-2" aria-label="Your review" onSubmit={(e) => e.preventDefault()}>
      {steps.length > 1 && (
        <label className="text-xs">Step{' '}
          <select value={step} onChange={(e) => setStep(e.target.value as 'check' | 'approve')} className="rounded-md border bg-background px-1 py-0.5">
            {steps.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      )}
      <p className="text-xs text-muted-foreground">
        Compare the value with the page yourself. Other reviewers’ answers stay hidden until you give yours.
      </p>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Note (required for wrong, unclear, reject)"
                aria-label="Note" className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <EvidenceInput id={id} busy={busy} actions={actions} onUploaded={setFileId} />
      <div className="flex flex-wrap gap-2">
        {step === 'check' ? (
          <>
            <Button size="sm" type="button" disabled={busy} onClick={() => send('correct')}>Correct</Button>
            <Button size="sm" variant="outline" type="button" disabled={busy} onClick={() => needNote('wrong')}>Wrong</Button>
            <Button size="sm" variant="outline" type="button" disabled={busy} onClick={() => needNote('unclear')}>Unclear</Button>
          </>
        ) : (
          <>
            <Button size="sm" type="button" disabled={busy} onClick={() => send('approve')}>Approve</Button>
            <Button size="sm" variant="outline" type="button" disabled={busy} onClick={() => needNote('reject')}>Reject</Button>
          </>
        )}
      </div>
      {step === 'check' && (
        <fieldset className="flex flex-col gap-2 rounded-md border p-2">
          <legend className="px-1 text-xs">Correct it (optional)</legend>
          <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={2} aria-label="Corrected value (JSON)"
                    placeholder='Corrected value, as JSON' className="w-full min-w-0 rounded-md border bg-background px-2 py-1 font-mono text-xs" />
          <textarea value={quote} onChange={(e) => setQuote(e.target.value)} rows={2} aria-label="Corrected quote"
                    placeholder="The words on the page" className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
          <Button size="sm" variant="outline" type="button" disabled={busy || !value.trim()} onClick={correct}>Send correction</Button>
        </fieldset>
      )}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </form>
  );
}

function EvidenceInput({ id, busy, actions, onUploaded }: {
  id: number; busy: boolean; actions: ReviewActions; onUploaded: (fileId: number) => void;
}) {
  const [name, setName] = useState<string | null>(null);
  return (
    <label className="text-xs">Evidence file (scan, screenshot or PDF){' '}
      <input type="file" disabled={busy} aria-label="Evidence file"
             onChange={async (e) => {
               const f = e.target.files?.[0];
               if (!f) return;
               onUploaded(await actions.upload(id, f));
               setName(f.name);
             }} />
      {name && <span> · {name} uploaded</span>}
    </label>
  );
}

function CollectForm({ detail, busy, actions }: { detail: OsReviewDetail; busy: boolean; actions: ReviewActions }) {
  const [value, setValue] = useState(detail.fact ? showValue(detail.fact.value) : '');
  const [quote, setQuote] = useState('');
  const [url, setUrl] = useState(detail.fact?.url ?? '');
  const [language, setLanguage] = useState('');
  const [note, setNote] = useState('');
  const [fileId, setFileId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = detail.item.id;
  const submit = () => {
    const parsed = parseValue(value);
    if (!parsed.ok) return setError('The value must be valid JSON.');
    if (!quote.trim() || !url.trim()) return setError('The exact quote and the page URL are required.');
    if (fileId === null) return setError('Upload the original as evidence first.');
    setError(null);
    void actions.collect(id, { value: parsed.value, quote: quote.trim(), url: url.trim(), language: language.trim() || null,
                               note: note.trim() || null, evidence_file_id: fileId });
  };
  return (
    <form className="mt-4 flex flex-col gap-2" aria-label="Your reading" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <p className="text-xs text-muted-foreground">
        Read the original yourself. A different reviewer compares your reading with the original before it counts.
      </p>
      <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={2} aria-label="Value (JSON)"
                className="w-full min-w-0 rounded-md border bg-background px-2 py-1 font-mono text-xs" />
      <textarea value={quote} onChange={(e) => setQuote(e.target.value)} rows={2} aria-label="Exact quote"
                placeholder="The exact words, in the original language" className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <input value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Page URL" placeholder="Page URL"
             className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <input value={language} onChange={(e) => setLanguage(e.target.value)} aria-label="Language code" placeholder="Language code, e.g. en"
             className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} aria-label="Note"
                className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <EvidenceInput id={id} busy={busy} actions={actions} onUploaded={setFileId} />
      <Button size="sm" type="submit" disabled={busy}>Save reading</Button>
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </form>
  );
}

function ResolveForm({ id, busy, actions }: { id: number; busy: boolean; actions: ReviewActions }) {
  const [note, setNote] = useState('');
  return (
    <form className="mt-4 flex flex-col gap-2" aria-label="Close this item" onSubmit={(e) => e.preventDefault()}>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="What you checked" aria-label="Note"
                className="w-full min-w-0 rounded-md border bg-background px-2 py-1" />
      <div className="flex gap-2">
        <Button size="sm" type="button" disabled={busy || !note.trim()} onClick={() => void actions.resolve(id, 'resolved', note.trim())}>Resolved</Button>
        <Button size="sm" variant="outline" type="button" disabled={busy || !note.trim()} onClick={() => void actions.resolve(id, 'dismissed', note.trim())}>Dismiss</Button>
      </div>
    </form>
  );
}
