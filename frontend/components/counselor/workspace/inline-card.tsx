"use client";
import {useState, type ReactNode} from 'react';
import {Button} from '@/components/ui/button';
import {workspaceApi} from '@/lib/api';
import {useWorkspace} from '@/lib/workspace-context';
import copy from './copy.json';
export type InlineCard = {kind: 'first_picture' | 'rating'; min?: number; max?: number};
export function ConversationCard({card, channel, children}: {card?: InlineCard; channel: string; children: ReactNode}) {
  const {currentUser} = useWorkspace();
  const [value,setValue]=useState<number|null>(null), [busy,setBusy]=useState(false), [saved,setSaved]=useState(false), [error,setError]=useState(false);
  if (!card) return <>{children}</>;
  async function send() {
    if (value === null || !currentUser) return;
    setBusy(true); setError(false);
    try {
      await workspaceApi.sendMessage(channel, copy.certaintyReply.replace('{value}',String(value)).replace('{max}',String(card?.max ?? 10)), currentUser.name, undefined, undefined, currentUser.id);
      setSaved(true);
    } catch {setError(true);} finally {setBusy(false);}
  }
  return <section className="rounded-2xl border border-primary/20 bg-primary/5 p-5" aria-label={card.kind === 'first_picture' ? copy.firstPicture : copy.certainty}>
    {card.kind === 'first_picture' && <h3 className="mb-3 font-semibold">{copy.firstPicture}</h3>}
    {children}
    {card.kind === 'rating' && (saved ? <p role="status" className="mt-3">{copy.saved}</p> : <div className="mt-4">
      <div className="flex flex-wrap gap-2" role="group" aria-label={copy.certainty}>
        {Array.from({length: (card.max ?? 10) - (card.min ?? 0) + 1},(_,i)=>i+(card.min ?? 0)).map(n=><Button key={n} variant={value===n?'primary':'outline'} aria-pressed={value===n} onClick={()=>setValue(n)}>{n}</Button>)}
      </div>
      <Button className="mt-4" disabled={value===null || busy} onClick={send}>{copy.sendRating}</Button>
      {error && <p role="alert">{copy.error}</p>}
    </div>)}
  </section>;
}
