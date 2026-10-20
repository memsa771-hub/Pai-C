"use client";
import {useState, type ReactNode} from 'react';
import {Check, SlidersHorizontal, Sparkles} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {workspaceApi} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace-context';
import {cn} from '@/lib/utils';
import copy from './copy.json';
export type InlineCard = {kind: 'first_picture' | 'rating'; min?: number; max?: number};

/** Wraps a counselor message that carries a card. The text stays PAI's own
 * words; the card only adds structure (a first picture) or a student action
 * (a rating, which is sent as the student's own message, never written). */
export function ConversationCard({card, channel, children}: {card?: InlineCard; channel: string; children: ReactNode}) {
  const {currentUser} = useWorkspace();
  const [value,setValue]=useState<number|null>(null), [busy,setBusy]=useState(false), [saved,setSaved]=useState(false), [error,setError]=useState(false);
  if (!card) return <>{children}</>;
  const min = card.min ?? 0, max = card.max ?? 10;
  async function send() {
    if (value === null || !currentUser) return;
    setBusy(true); setError(false);
    try {
      await workspaceApi.sendMessage(channel, copy.certaintyReply.replace('{value}',String(value)).replace('{max}',String(max)), currentUser.name, undefined, undefined, currentUser.id);
      setSaved(true);
    } catch {setError(true);} finally {setBusy(false);}
  }
  const first = card.kind === 'first_picture';
  return <section className="-mx-1 overflow-hidden rounded-2xl" aria-label={first ? copy.firstPicture : copy.ratingTitle}>
    {first && <div className="mb-3 flex items-center gap-2.5">
      <span aria-hidden className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-[var(--hero-from)] to-[var(--hero-via)] text-white"><Sparkles className="size-[18px]"/></span>
      <h3 className="font-bold">{copy.firstPicture}</h3>
    </div>}
    {!first && <div aria-hidden className="mb-2 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><SlidersHorizontal className="size-4"/>{copy.ratingTitle}</div>}
    <div className={cn(first && 'rounded-2xl border-l-4 border-foreground bg-secondary ring-1 ring-foreground/50 px-4 py-3')}>{children}</div>
    {card.kind === 'rating' && (saved ? <p role="status" className="mt-3 flex items-center gap-2 font-medium text-success-ink"><Check aria-hidden className="size-4"/>{copy.ratingSent}</p> : <div className="mt-4">
      <div className="grid grid-cols-6 gap-1.5 sm:grid-cols-11" role="group" aria-label={copy.ratingTitle}>
        {Array.from({length: max - min + 1},(_,i)=>i+min).map(n=>{
          // A cool-to-warm ramp reads as "how sure", without implying a grade.
          const strength = (n - min) / Math.max(1, max - min);
          return <button key={n} type="button" aria-pressed={value===n} onClick={()=>setValue(n)}
            className={cn('flex h-11 items-center justify-center rounded-xl border-2 text-sm font-bold transition-colors',
              value===n ? 'border-primary bg-primary text-primary-foreground' : 'border-transparent bg-muted hover:border-foreground/30')}
            style={value===n ? undefined : {backgroundColor: `color-mix(in oklab, var(--brand) ${Math.round(6 + strength * 22)}%, var(--muted))`}}>{n}</button>;
        })}
      </div>
      <div aria-hidden className="mt-1.5 flex justify-between text-xs text-muted-foreground"><span>{copy.ratingLow}</span><span>{copy.ratingHigh}</span></div>
      <Button size="tap" className="mt-3" disabled={value===null || busy} onClick={send}>{copy.sendRating}</Button>
      {error && <p role="alert" className="mt-2 text-sm font-medium text-danger-ink">{copy.error}</p>}
    </div>)}
  </section>;
}
