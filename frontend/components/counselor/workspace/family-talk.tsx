"use client";
import { useState } from "react";
import { workspaceApi } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useResource, LoadState } from "./resource";
import copy from "./family-talk.json";
import common from "./copy.json";
const load = () => workspaceApi.getFamilyTalk();
export function FamilyTalk() {
  const resource = useResource(load);
  const [personId, setPerson] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [submission, setSubmission] = useState<string | null>(null);
  if (!resource.data || resource.error) return <LoadState error={resource.error} busy={resource.busy} retry={resource.refresh} />;
  const guide = resource.data;
  const person = guide.family.find(p => p.id === personId);
  async function prepare() {
    if (!guide.path_id) return;
    setBusy(true); setError(false);
    const id = submission || crypto.randomUUID(); setSubmission(id);
    try { const response = await workspaceApi.prepareFamilyTalk({submission_id:id,path_id:guide.path_id,person_id:personId,evidence_ids:selected}); setResult(response.script); }
    catch { setError(true); } finally { setBusy(false); }
  }
  return <section className="my-6 space-y-4 rounded-2xl border bg-card p-6">
    <h2 className="text-xl font-semibold">{copy.title}</h2><p className="text-sm text-muted-foreground">{guide.message}</p>
    {guide.ready && !result && <>
      <fieldset disabled={busy} className="space-y-3"><legend className="mb-2 text-sm font-medium">{copy.person}</legend>
        {guide.family.map(p => <label key={p.id} className="mr-5 inline-flex items-center gap-2"><input type="radio" name="family-person" value={p.id} checked={personId===p.id} onChange={()=>{setPerson(p.id);setSubmission(null);}} />{p.role}</label>)}
      </fieldset>
      {person && <div className="rounded-xl bg-muted/50 p-4 text-sm"><p className="font-medium">{copy.concern}</p><p className="mt-1">{person.worry || copy.noWorry}</p>{person.wish && <><p className="mt-3 font-medium">{copy.wish}</p><p>{person.wish}</p></>}<blockquote className="mt-3 border-l-2 pl-3 text-muted-foreground">{person.evidence}</blockquote></div>}
      <fieldset disabled={busy} className="space-y-3"><legend className="text-sm font-medium">{copy.evidence}</legend><p className="text-xs text-muted-foreground">{copy.evidenceHelp}</p>
        {guide.evidence.map(e=><label key={e.id} className="flex items-start gap-3 rounded-xl border p-3 text-sm"><input className="mt-1" type="checkbox" checked={selected.includes(e.id)} onChange={()=>{setSelected(old=>old.includes(e.id)?old.filter(id=>id!==e.id):old.length<5?[...old,e.id]:old);setSubmission(null);}} />{e.quote}</label>)}
      </fieldset>
      <Button disabled={busy || !person?.worry || !selected.length} onClick={()=>void prepare()}>{busy?common.loading:copy.prepare}</Button>
    </>}
    {error && <p role="alert" className="text-sm text-destructive">{common.error}</p>}
    {result && <div role="status"><h3 className="font-medium">{copy.prepared}</h3><p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{result}</p></div>}
  </section>;
}
