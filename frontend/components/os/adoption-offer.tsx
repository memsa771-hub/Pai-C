'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { adoptionRefusalText, type Adoption } from '@/lib/os-connect';
import copy from '@/components/counselor/workspace/copy.json';

const WHY_NOT = ['several_plans', 'identity_taken', 'no_places', 'no_intake'];

/** True when the offer shows something: the offer itself, or the reason there is none (several plans, a plan already held, no places, no start date). */
export function adoptionShows(a: Adoption | null): boolean {
  return !!a && (a.offer ? !!a.text && !!a.plan : WHY_NOT.includes(a.state ?? ''));
}

/** The offer to keep a plan the student built themselves as their PAI plan (P1-T6, R-08). Every sentence is the
 * server's (`text`); with no text, or no offer, nothing shows. "Agree" is there only while the state is `ready`. */
export function AdoptionOffer({ adoption }: { adoption: Adoption | null }) {
  const [state, setState] = useState<string | null>(null);  // the answer to our own POST, when there is one
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const text = adoption?.text;
  if (adoption && !adoption.offer && WHY_NOT.includes(adoption.state ?? '')) {  // no offer: say why
    return (
      <section aria-label={(copy.connect.adoption as Record<string, string>)[adoption.state as string]} className="mb-6 rounded-[22px] bg-card p-5 shadow-card ring-1 ring-border/70">
        <p role="status" className="text-sm">{(copy.connect.adoption as Record<string, string>)[adoption.state as string]}</p>
      </section>
    );
  }
  if (!adoption || !adoption.offer || !text || !adoption.plan) return null;
  const shown = state ?? adoption.state;
  if (shown !== 'ready' && shown !== 'linking' && shown !== 'linked' && shown !== 'choose_field_first' && shown !== 'too_many_places') return null;
  const agree = async () => {
    setBusy(true);
    setRefusal(null);
    try {
      setState((await workspaceApi.adoptPlan(adoption.plan!.plan_id)).state);
    } catch (e) {
      setRefusal(adoptionRefusalText(e, copy.connect, text));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-label={text.offer} className="mb-6 rounded-[22px] bg-card p-5 shadow-card ring-1 ring-border/70">
      {shown === 'ready' && (
        <>
          <p className="text-sm">{text.offer}</p>
          <Button size="sm" className="mt-3" disabled={busy} onClick={agree}>{text.agree}</Button>
        </>
      )}
      {shown === 'linking' && (
        <p role="status" className="text-sm">{text.linking} <span className="text-muted-foreground">{copy.connect.adoption.linking_wait}</span></p>
      )}
      {(shown === 'choose_field_first' || shown === 'too_many_places') && <p role="status" className="text-sm">{text[shown]}</p>}
      {shown === 'linked' && <p role="status" className="text-sm">{copy.connect.adoption.linked}</p>}
      {refusal && <p role="alert" className="mt-2 break-words text-sm text-destructive">{refusal}</p>}
    </section>
  );
}
