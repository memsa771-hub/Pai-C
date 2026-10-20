"use client";
import { useState } from "react";
import { Check, CircleAlert, Heart, Loader2 } from "lucide-react";
import { workspaceApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { toneClass, toneFor } from "@/components/pai";
import { cn } from "@/lib/utils";
import { useResource, LoadState } from "./resource";
import copy from "./family-talk.json";
import common from "./copy.json";
const load = () => workspaceApi.getFamilyTalk();

/** Prepare a family conversation from the student's own evidence. Embedded
 * in a section that already carries the title, so none is repeated here. */
export function FamilyTalk() {
  const resource = useResource(load);
  const [personId, setPerson] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [submission, setSubmission] = useState<string | null>(null);
  if (!resource.data || resource.error) return <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} skeleton="list" />;
  const guide = resource.data;
  const person = guide.family.find((p) => p.id === personId);
  async function prepare() {
    if (!guide.path_id) return;
    setBusy(true); setError(false);
    const id = submission || crypto.randomUUID(); setSubmission(id);
    try { const response = await workspaceApi.prepareFamilyTalk({ submission_id: id, path_id: guide.path_id, person_id: personId, evidence_ids: selected }); setResult(response.script); }
    catch { setError(true); } finally { setBusy(false); }
  }
  const card = (on: boolean) => cn("flex min-h-12 cursor-pointer items-center gap-3 rounded-2xl border-2 px-4 py-3 text-sm transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring",
    on ? "border-brand bg-brand-soft" : "border-border hover:border-brand/40");
  return <div className="space-y-5">
    <p className="text-sm text-muted-foreground">{guide.message}</p>
    {guide.ready && !result && <>
      <fieldset disabled={busy}>
        <legend className="mb-2 text-sm font-semibold">{copy.person}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {guide.family.map((p) => {
            const tone = toneFor(p.role);
            return <label key={p.id} className={card(personId === p.id)}>
              <input type="radio" name="family-person" value={p.id} checked={personId === p.id} className="sr-only"
                onChange={() => { setPerson(p.id); setSubmission(null); }} />
              <span aria-hidden className={cn("flex size-9 shrink-0 items-center justify-center rounded-full font-bold", toneClass[tone].solid)}>{p.role.charAt(0)}</span>
              <span className="font-semibold">{p.role}</span>
            </label>;
          })}
        </div>
      </fieldset>
      {person && <div className="grid gap-3 rounded-2xl bg-muted/60 p-4 text-sm sm:grid-cols-2">
        <div><p className="flex items-center gap-1.5 font-semibold"><CircleAlert aria-hidden className="size-4 text-tone-amber" />{copy.concern}</p><p className="mt-1">{person.worry || copy.noWorry}</p></div>
        {person.wish && <div><p className="flex items-center gap-1.5 font-semibold"><Heart aria-hidden className="size-4 text-tone-teal" />{copy.wish}</p><p className="mt-1">{person.wish}</p></div>}
        <blockquote className="border-l-4 border-border pl-3 text-muted-foreground sm:col-span-2">“{person.evidence}”</blockquote>
      </div>}
      <fieldset disabled={busy} className="space-y-2">
        <legend className="text-sm font-semibold">{copy.evidence}</legend>
        <p className="text-xs text-muted-foreground">{copy.evidenceHelp}</p>
        {guide.evidence.map((e) => <label key={e.id} className={card(selected.includes(e.id))}>
          <input type="checkbox" className="size-5 shrink-0 accent-[var(--brand)]" checked={selected.includes(e.id)}
            onChange={() => { setSelected((old) => old.includes(e.id) ? old.filter((id) => id !== e.id) : old.length < 5 ? [...old, e.id] : old); setSubmission(null); }} />
          <span>“{e.quote}”</span>
        </label>)}
      </fieldset>
      <Button size="tap" disabled={busy || !person?.worry || !selected.length} onClick={() => void prepare()}>
        {busy ? <><Loader2 aria-hidden className="animate-spin" />{common.loading}</> : copy.prepare}
      </Button>
    </>}
    {error && <p role="alert" className="text-sm font-medium text-danger-ink">{common.error}</p>}
    {result && <div role="status" className="rounded-2xl bg-success-soft p-4">
      <h3 className="flex items-center gap-2 font-semibold text-success-ink"><Check aria-hidden className="size-4" />{copy.prepared}</h3>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{result}</p>
    </div>}
  </div>;
}
