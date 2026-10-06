'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, Check, ClipboardList, ExternalLink, GraduationCap,
  Loader2, Plus, Search, Sparkles, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import { useWorkspace } from '@/lib/workspace-context';
import type { ApplicationPlan, ApplicationRequirement, ApplicationStatus, Institution } from '@/lib/application-workspace';
import { ApplicationCalendar } from './application-calendar';
import { ApplicationOperations } from './application-operations';

type Section = 'overview' | 'colleges' | 'search' | 'calendar';
const inputClass = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15';
const statusLabels: Record<ApplicationStatus, string> = {
  planning: 'Planning', preparing: 'Preparing', ready: 'Ready to submit',
  submitted: 'Submitted elsewhere', decision: 'Decision received', withdrawn: 'Withdrawn',
};

function dateLabel(value: string | null) {
  if (!value) return 'No deadline added';
  return new Intl.DateTimeFormat(undefined, { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(new Date(value));
}

function safeLink(value: string | null) {
  if (!value) return null;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

function localToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export function ApplicationsView() {
  const { files } = useWorkspace();
  const [section, setSection] = useState<Section>('overview');
  const [saved, setSaved] = useState<Institution[]>([]);
  const [plans, setPlans] = useState<ApplicationPlan[]>([]);
  const [results, setResults] = useState<Institution[]>([]);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ApplicationPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [newSchool, setNewSchool] = useState({ name: '', country_code: '', city: '', website_url: '' });
  const [newPlanSchool, setNewPlanSchool] = useState<Institution | null>(null);
  const [newPlan, setNewPlan] = useState({ program_name: '', intake: '', route: '', deadline_at: '', application_url: '' });
  const [requirement, setRequirement] = useState({ label: '', kind: 'other', due_at: '', source_url: '' });

  const refresh = useCallback(async () => {
    const [nextSaved, nextPlans] = await Promise.all([workspaceApi.getSavedInstitutions(), workspaceApi.getApplications()]);
    setSaved(nextSaved);
    setPlans(nextPlans);
  }, []);

  useEffect(() => {
    if (!workspaceApi.isConfigured()) return;
    let live = true;
    Promise.all([workspaceApi.getSavedInstitutions(), workspaceApi.getApplications()])
      .then(([nextSaved, nextPlans]) => { if (live) { setSaved(nextSaved); setPlans(nextPlans); } })
      .catch(() => { if (live) setError('Could not load applications. Please retry.'); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (section !== 'search') return;
    let live = true;
    const timer = window.setTimeout(() => {
      workspaceApi.searchInstitutions(query)
        .then((rows) => { if (live) setResults(rows); })
        .catch(() => { if (live) setError('College search is unavailable.'); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, section, saved]);

  useEffect(() => {
    if (!selectedId) { setSelected(null); return; }
    let live = true;
    workspaceApi.getApplication(selectedId)
      .then((plan) => { if (live) setSelected(plan); })
      .catch(() => { if (live) setError('Could not open this application.'); });
    return () => { live = false; };
  }, [selectedId]);

  async function act(action: () => Promise<unknown>, onSuccess?: () => void) {
    setBusy(true); setError('');
    try {
      await action();
      await refresh();
      if (selectedId) setSelected(await workspaceApi.getApplication(selectedId));
      onSuccess?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save your changes.');
    } finally { setBusy(false); }
  }

  const activePlans = plans.filter((plan) => plan.status !== 'withdrawn');
  const upcoming = activePlans.filter((plan) => plan.deadline_at && plan.deadline_at.slice(0, 10) >= localToday())
    .sort((a, b) => (a.deadline_at || '').localeCompare(b.deadline_at || ''))[0];

  if (loading) return <div className="flex h-full items-center justify-center text-muted-foreground"><Loader2 className="mr-2 size-4 animate-spin" />Loading applications…</div>;

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="mx-auto w-full max-w-6xl px-5 py-8 sm:px-8 lg:py-10">
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary"><GraduationCap className="size-4" /> Student workspace</div>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Applications</h1>
            <p className="mt-2 max-w-2xl text-sm text-muted-foreground">Keep your colleges, programs and application work in one place. Add only the requirements that apply to you.</p>
          </div>
          <Button onClick={() => { setSection('search'); setSelectedId(null); }}><Plus className="mr-2 size-4" />Add a college</Button>
        </div>

        {error && <div role="alert" className="mb-5 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"><span>{error}</span><div className="flex items-center gap-3"><button type="button" className="font-semibold underline" onClick={() => { setError(''); refresh().catch(() => setError('Could not load applications. Please retry.')); }}>Retry</button><button type="button" onClick={() => setError('')} aria-label="Dismiss error">×</button></div></div>}

        {selected ? (
          <div>
            <button type="button" className="mb-5 flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground" onClick={() => { setSelectedId(null); setSelected(null); }}><ArrowLeft className="size-4" />Back to applications</button>
            <div className="rounded-2xl border bg-card p-5 shadow-sm sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Application plan</p><h2 className="mt-1 text-2xl font-semibold">{selected.institution.name}</h2><p className="mt-1 text-sm text-muted-foreground">{selected.program_name || 'Program not added yet'} · {selected.intake || 'Intake not added yet'}</p></div>
                <select aria-label="Application status" className={inputClass + ' max-w-52'} value={selected.status} disabled={busy} onChange={(event) => act(() => workspaceApi.updateApplication(selected.id, { status: event.target.value as ApplicationStatus }))}>
                  {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">Status is your own record. PAI has not submitted or verified this application with the institution.</p>
              <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Program or course" value={selected.program_name || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { program_name: value }))} />
                <Field label="Intake" value={selected.intake || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { intake: value }))} />
                <Field label="Application route" value={selected.route || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { route: value }))} />
                <Field label="Deadline" type="date" value={selected.deadline_at?.slice(0, 10) || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { deadline_at: value ? new Date(`${value}T12:00:00Z`).toISOString() : null }))} />
                <Field label="Application URL" type="url" value={selected.application_url || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { application_url: value || null }))} />
                <Field label="Submission reference" value={selected.submission_reference || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { submission_reference: value }))} />
              </div>
              {safeLink(selected.application_url) && <a className="mt-5 inline-flex items-center gap-1 text-sm text-primary hover:underline" href={safeLink(selected.application_url)!} target="_blank" rel="noopener noreferrer">Open application website <ExternalLink className="size-3.5" /></a>}
            </div>

            <div className="mt-6 rounded-2xl border bg-card p-5 shadow-sm sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><h3 className="text-xl font-semibold">Requirements & work</h3><p className="mt-1 text-sm text-muted-foreground">Build a checklist from the college’s official requirements. Link a task when you want to organize the work.</p></div><span className="rounded-full bg-muted px-3 py-1 text-xs font-medium">{(selected.requirements || []).filter((item) => item.status === 'done').length} done / {(selected.requirements || []).length} total</span></div>
              <div className="mt-6 space-y-2">
                {(selected.requirements || []).length === 0 && <p className="rounded-xl border border-dashed p-6 text-center text-sm text-muted-foreground">No requirements yet. Check the official application page, then add each item here.</p>}
                {(selected.requirements || []).map((item) => <RequirementRow key={item.id} item={item} busy={busy} files={files.filter((file) => file.status === 'active')}
                  onChange={(status) => act(() => workspaceApi.updateApplicationRequirement(selected.id, item.id, { status }))}
                  onFile={(fileId) => act(() => workspaceApi.updateApplicationRequirement(selected.id, item.id, { file_id: fileId || null }))}
                  onTask={() => act(() => workspaceApi.ensureApplicationTask(selected.id, item.id))}
                  onDelete={() => act(() => workspaceApi.deleteApplicationRequirement(selected.id, item.id))} />)}
              </div>
              <form className="mt-6 grid gap-3 border-t pt-5 sm:grid-cols-[1fr_10rem_10rem_auto]" onSubmit={(event) => { event.preventDefault(); if (!requirement.label.trim()) return; act(() => workspaceApi.addApplicationRequirement(selected.id, { label: requirement.label.trim(), kind: requirement.kind, due_at: requirement.due_at ? new Date(`${requirement.due_at}T12:00:00Z`).toISOString() : null, source_url: requirement.source_url || null }), () => setRequirement({ label: '', kind: 'other', due_at: '', source_url: '' })); }}>
                <input className={inputClass} aria-label="Requirement" placeholder="e.g. Transcript, essay, recommendation" value={requirement.label} onChange={(event) => setRequirement({ ...requirement, label: event.target.value })} required />
                <input className={inputClass} aria-label="Requirement type" placeholder="Type" value={requirement.kind} onChange={(event) => setRequirement({ ...requirement, kind: event.target.value })} />
                <input className={inputClass} aria-label="Due date" type="date" value={requirement.due_at} onChange={(event) => setRequirement({ ...requirement, due_at: event.target.value })} />
                <Button type="submit" disabled={busy}><Plus className="mr-1 size-4" />Add</Button>
                <input className={inputClass + ' sm:col-span-4'} aria-label="Official requirement source URL" type="url" placeholder="Official requirement URL (optional)" value={requirement.source_url} onChange={(event) => setRequirement({ ...requirement, source_url: event.target.value })} />
              </form>
            </div>
            <ApplicationOperations plan={selected} onRefresh={async () => { await refresh(); setSelected(await workspaceApi.getApplication(selected.id)); }} />
            <div className="mt-6 rounded-2xl border bg-card p-5 shadow-sm sm:p-7"><h3 className="text-lg font-semibold">Notes</h3><Field multiline label="Your application notes" value={selected.notes || ''} onSave={(value) => act(() => workspaceApi.updateApplication(selected.id, { notes: value }))} /></div>
          </div>
        ) : (
          <>
            <div className="mb-6 flex flex-wrap gap-2 border-b pb-3">
              {([['overview', 'Overview'], ['colleges', 'My colleges'], ['search', 'College search'], ['calendar', 'Calendar']] as const).map(([key, label]) => <button key={key} type="button" className={`rounded-lg px-4 py-2 text-sm font-medium ${section === key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`} onClick={() => setSection(key)}>{label}</button>)}
            </div>
            {section === 'overview' && <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat icon={<BookOpen className="size-5" />} label="Saved colleges" value={saved.length} />
                <Stat icon={<ClipboardList className="size-5" />} label="Application plans" value={activePlans.length} />
                <div className="rounded-2xl border bg-card p-5 shadow-sm"><p className="text-sm text-muted-foreground">Next deadline</p><p className="mt-3 text-lg font-semibold">{upcoming ? dateLabel(upcoming.deadline_at) : 'Nothing scheduled'}</p><p className="mt-1 truncate text-xs text-muted-foreground">{upcoming?.institution.name || 'Add a deadline to a plan'}</p></div>
              </div>
              <div className="mt-8 flex items-center justify-between"><h2 className="text-xl font-semibold">My applications</h2><Button variant="outline" onClick={() => setSection('colleges')}>My colleges <ArrowRight className="ml-2 size-4" /></Button></div>
              {plans.length === 0 ? <Empty title="Start with a college" body="Search your saved colleges or add one yourself. Then create an application plan for a program and intake." action={() => setSection('search')} /> : <div className="mt-4 grid gap-3 md:grid-cols-2">{plans.map((plan) => <button key={plan.id} type="button" onClick={() => setSelectedId(plan.id)} className="rounded-2xl border bg-card p-5 text-left shadow-sm transition-colors hover:border-primary/40 hover:bg-accent/30"><div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold">{plan.institution.name}</h3><p className="mt-1 text-sm text-muted-foreground">{plan.program_name || 'Add a program'}{plan.intake ? ` · ${plan.intake}` : ''}</p></div><ArrowRight className="size-4 shrink-0 text-muted-foreground" /></div><div className="mt-5 flex items-center justify-between text-xs"><span className="rounded-full bg-muted px-2.5 py-1 font-medium">{statusLabels[plan.status]}</span><span className="text-muted-foreground">{dateLabel(plan.deadline_at)}</span></div></button>)}</div>}
            </>}
            {section === 'colleges' && <><div className="mb-5 flex items-center justify-between"><div><h2 className="text-xl font-semibold">My colleges</h2><p className="mt-1 text-sm text-muted-foreground">Save colleges first. Create separate plans for each program or intake.</p></div></div>{saved.length === 0 ? <Empty title="No colleges saved" body="Search the catalog or add your college to your private list." action={() => setSection('search')} /> : <div className="grid gap-3 md:grid-cols-2">{saved.map((school) => <SchoolCard key={school.id} school={school} plans={plans.filter((plan) => plan.institution.id === school.id)} busy={busy} onPlan={() => setNewPlanSchool(school)} onSave={() => {}} onUnsave={() => act(() => workspaceApi.unsaveInstitution(school.id))} />)}</div>}</>}
            {section === 'calendar' && <ApplicationCalendar onOpen={(id) => setSelectedId(id)} />}
            {section === 'search' && <><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-xl font-semibold">College search</h2><p className="mt-1 text-sm text-muted-foreground">Search available colleges, or add one privately if it is not listed yet.</p></div><Button variant="outline" onClick={() => setShowAdd(!showAdd)}><Plus className="mr-1 size-4" />Add college yourself</Button></div>
              <div className="relative mt-5"><Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" /><input className={inputClass + ' pl-10'} placeholder="Search colleges and universities" aria-label="Search colleges" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
              {showAdd && <form className="mt-5 rounded-2xl border bg-card p-5" onSubmit={(event) => { event.preventDefault(); act(() => workspaceApi.addInstitution(newSchool), () => { setShowAdd(false); setNewSchool({ name: '', country_code: '', city: '', website_url: '' }); setSection('colleges'); }); }}><h3 className="mb-4 font-semibold">Add a college to your list</h3><div className="grid gap-3 sm:grid-cols-2"><input className={inputClass} placeholder="Official college name" aria-label="College name" required minLength={2} value={newSchool.name} onChange={(event) => setNewSchool({ ...newSchool, name: event.target.value })} /><input className={inputClass} placeholder="Country code (e.g. US, GB)" aria-label="Two-letter country code" required maxLength={2} minLength={2} pattern="[A-Za-z]{2}" value={newSchool.country_code} onChange={(event) => setNewSchool({ ...newSchool, country_code: event.target.value.toUpperCase() })} /><input className={inputClass} placeholder="City (optional)" aria-label="City" value={newSchool.city} onChange={(event) => setNewSchool({ ...newSchool, city: event.target.value })} /><input className={inputClass} placeholder="Official website (optional)" aria-label="Official website" type="url" value={newSchool.website_url} onChange={(event) => setNewSchool({ ...newSchool, website_url: event.target.value })} /></div><p className="my-4 text-xs text-muted-foreground">Student-added college details are private and unverified. Check the official website before making decisions.</p><Button type="submit" disabled={busy}>Save college</Button></form>}
              <div className="mt-5 grid gap-3 md:grid-cols-2">{results.map((school) => <SchoolCard key={school.id} school={school} plans={plans.filter((plan) => plan.institution.id === school.id)} busy={busy} onPlan={() => setNewPlanSchool(school)} onSave={() => act(() => workspaceApi.saveInstitution(school.id))} onUnsave={() => act(() => workspaceApi.unsaveInstitution(school.id))} />)}</div>
              {results.length === 0 && !showAdd && <Empty title="No colleges found" body="The catalog grows as colleges are added. Add the college yourself to start planning now." action={() => setShowAdd(true)} />}
            </>}
          </>
        )}
      </div>

      {newPlanSchool && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setNewPlanSchool(null); }}><form role="dialog" aria-modal="true" aria-label="New application plan" className="w-full max-w-lg rounded-2xl border bg-background p-6 shadow-xl" onSubmit={(event) => { event.preventDefault(); act(async () => { const plan = await workspaceApi.createApplication({ institution_id: newPlanSchool.id, program_name: newPlan.program_name, intake: newPlan.intake, route: newPlan.route, deadline_at: newPlan.deadline_at ? new Date(`${newPlan.deadline_at}T12:00:00Z`).toISOString() : null, application_url: newPlan.application_url || null }); setSelectedId(plan.id); }, () => { setNewPlanSchool(null); setNewPlan({ program_name: '', intake: '', route: '', deadline_at: '', application_url: '' }); }); }}><div className="mb-5"><h2 className="text-xl font-semibold">Plan an application</h2><p className="mt-1 text-sm text-muted-foreground">{newPlanSchool.name}</p></div><div className="space-y-3"><input className={inputClass} aria-label="Program or course" placeholder="Program or course (optional)" value={newPlan.program_name} onChange={(event) => setNewPlan({ ...newPlan, program_name: event.target.value })} /><input className={inputClass} aria-label="Intake" placeholder="Intake (e.g. Fall 2027)" value={newPlan.intake} onChange={(event) => setNewPlan({ ...newPlan, intake: event.target.value })} /><input className={inputClass} aria-label="Application route" placeholder="Application route (optional)" value={newPlan.route} onChange={(event) => setNewPlan({ ...newPlan, route: event.target.value })} /><label className="block text-xs text-muted-foreground">Deadline<input className={inputClass + ' mt-1'} type="date" value={newPlan.deadline_at} onChange={(event) => setNewPlan({ ...newPlan, deadline_at: event.target.value })} /></label><input className={inputClass} aria-label="Application website" type="url" placeholder="Application website (optional)" value={newPlan.application_url} onChange={(event) => setNewPlan({ ...newPlan, application_url: event.target.value })} /></div><p className="mt-4 text-xs text-muted-foreground">Deadlines and requirements are student-entered until an official integration verifies them.</p><div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" onClick={() => setNewPlanSchool(null)}>Cancel</Button><Button type="submit" disabled={busy}>Create plan</Button></div></form></div>}
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: number }) { return <div className="rounded-2xl border bg-card p-5 shadow-sm"><span className="text-primary">{icon}</span><p className="mt-4 text-3xl font-semibold tabular-nums">{value}</p><p className="mt-1 text-sm text-muted-foreground">{label}</p></div>; }
function Empty({ title, body, action }: { title: string; body: string; action: () => void }) { return <div className="mt-5 rounded-2xl border border-dashed bg-muted/20 px-6 py-12 text-center"><Sparkles className="mx-auto size-6 text-primary" /><h3 className="mt-3 font-semibold">{title}</h3><p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">{body}</p><Button className="mt-5" onClick={action}>Find a college <ArrowRight className="ml-2 size-4" /></Button></div>; }

function SchoolCard({ school, plans, busy, onPlan, onSave, onUnsave }: { school: Institution; plans: ApplicationPlan[]; busy: boolean; onPlan: () => void; onSave: () => void; onUnsave: () => void }) {
  const website = safeLink(school.website_url);
  return <div className="rounded-2xl border bg-card p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div><h3 className="font-semibold">{school.name}</h3><p className="mt-1 text-sm text-muted-foreground">{[school.city, school.country_code].filter(Boolean).join(', ')}</p></div><GraduationCap className="size-5 shrink-0 text-primary" /></div><p className="mt-3 text-xs text-muted-foreground">{school.source === 'student' ? 'Added by you · unverified' : `Catalog: ${school.provider || school.source}`} · {plans.length} application {plans.length === 1 ? 'plan' : 'plans'}</p><div className="mt-5 flex flex-wrap items-center gap-2"><Button size="sm" onClick={onPlan}><Plus className="mr-1 size-3.5" />Plan application</Button>{school.saved ? <Button size="sm" variant="ghost" onClick={onUnsave} disabled={busy}>Remove from list</Button> : <Button size="sm" variant="outline" onClick={onSave} disabled={busy}>Save college</Button>}{website && <a className="ml-auto inline-flex items-center gap-1 text-xs text-primary hover:underline" href={website} target="_blank" rel="noopener noreferrer">Website <ExternalLink className="size-3" /></a>}</div></div>;
}

function RequirementRow({ item, busy, files, onChange, onFile, onTask, onDelete }: { item: ApplicationRequirement; busy: boolean; files: { id: string; filename: string }[]; onChange: (status: ApplicationRequirement['status']) => void; onFile: (fileId: string) => void; onTask: () => void; onDelete: () => void }) {
  return <div className="flex flex-wrap items-center gap-3 rounded-xl border p-3"><button type="button" disabled={busy} onClick={() => onChange(item.status === 'done' ? 'todo' : 'done')} aria-label={`${item.status === 'done' ? 'Mark incomplete' : 'Mark done'}: ${item.label}`} className={`flex size-6 shrink-0 items-center justify-center rounded-full border ${item.status === 'done' ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40'}`}>{item.status === 'done' && <Check className="size-4" />}</button><div className="min-w-40 flex-1"><p className={`text-sm font-medium ${item.status === 'done' ? 'text-muted-foreground line-through' : ''}`}>{item.label}</p><p className="text-xs text-muted-foreground">{item.kind}{item.due_at ? ` · Due ${dateLabel(item.due_at)}` : ''}{item.task_id ? ` · Task ${item.task_status?.replace('_', ' ') || 'linked'}` : ''}</p></div>{safeLink(item.source_url) && <a href={safeLink(item.source_url)!} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">Source <ExternalLink className="inline size-3" /></a>}{files.length > 0 && <select aria-label={`Attached document for ${item.label}`} className="max-w-40 rounded-md border bg-background px-2 py-1 text-xs" value={item.file_id || ''} disabled={busy} onChange={(event) => onFile(event.target.value)}><option value="">Attach document</option>{files.map((file) => <option key={file.id} value={file.id}>{file.filename}</option>)}</select>}{!item.task_id && <Button variant="ghost" size="sm" onClick={onTask} disabled={busy}>Create task</Button>}<button type="button" onClick={onDelete} disabled={busy} aria-label={`Delete ${item.label}`} className="text-muted-foreground hover:text-destructive"><Trash2 className="size-4" /></button></div>;
}

function Field({ label, value, onSave, type = 'text', multiline = false }: { label: string; value: string; onSave: (value: string) => void; type?: string; multiline?: boolean }) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return <label className="block text-xs font-medium text-muted-foreground">{label}<div className="mt-1 flex items-start gap-1">{multiline ? <textarea className={inputClass + ' min-h-24'} value={draft} onChange={(event) => setDraft(event.target.value)} /> : <input className={inputClass} type={type} value={draft} onChange={(event) => setDraft(event.target.value)} />}{draft !== value && <Button type="button" size="sm" aria-label={`Save ${label}`} onClick={() => onSave(draft)}><Check className="size-4" /></Button>}</div></label>;
}
