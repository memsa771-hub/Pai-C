'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowRight, CalendarClock, Check, ChevronLeft, ChevronRight, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { workspaceApi } from '@/lib/api';
import type { DeadlineSettings, StudentDeadline } from '@/lib/student-deadlines';
import { useLayout } from '@/components/layout/layout-context';

const inputClass = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15';

function dateKey(value: Date) {
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
}

function todayInZone(zone: string) {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = (type: string) => parts.find((item) => item.type === type)?.value || '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}

function safeSource(value: string | null) {
  if (!value) return null;
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

export function DeadlinesView() {
  const { openView } = useLayout();
  const [anchor, setAnchor] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [items, setItems] = useState<StudentDeadline[]>([]);
  const [settings, setSettings] = useState<DeadlineSettings>({ timezone: 'UTC', reminder_days: [7, 1, 0, -1] });
  const [daysDraft, setDaysDraft] = useState('7, 1, 0, -1');
  const [zoneDraft, setZoneDraft] = useState('UTC');
  const [draft, setDraft] = useState({ title: '', due_on: '', category: '', notes: '', source_url: '' });
  const [editing, setEditing] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState({ title: '', due_on: '' });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);

  const range = useMemo(() => {
    const start = new Date(anchor.getFullYear(), anchor.getMonth() - 2, 1);
    const end = new Date(anchor.getFullYear(), anchor.getMonth() + 10, 0);
    return { start: dateKey(start), end: dateKey(end) };
  }, [anchor]);

  const load = useCallback(async () => {
    const result = await workspaceApi.getStudentDeadlines(range.start, range.end);
    setItems(result.deadlines);
    setSettings(result.settings);
    setDaysDraft(result.settings.reminder_days.join(', '));
    setZoneDraft(result.settings.timezone);
  }, [range]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    workspaceApi.getStudentDeadlines(range.start, range.end)
      .then((result) => { if (live) { setItems(result.deadlines); setSettings(result.settings); setDaysDraft(result.settings.reminder_days.join(', ')); setZoneDraft(result.settings.timezone); } })
      .catch(() => { if (live) setError('Deadlines could not load.'); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [range, version]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not save this deadline.'); }
    finally { setBusy(false); }
  }

  const today = todayInZone(settings.timezone);
  const plusSeven = new Date(`${today}T12:00:00Z`);
  plusSeven.setUTCDate(plusSeven.getUTCDate() + 7);
  const groups = [
    { label: 'Overdue', rows: items.filter((item) => item.status === 'open' && item.date < today) },
    { label: 'Next 7 days', rows: items.filter((item) => item.status === 'open' && item.date >= today && item.date <= plusSeven.toISOString().slice(0, 10)) },
    { label: 'Later', rows: items.filter((item) => item.status === 'open' && item.date > plusSeven.toISOString().slice(0, 10)) },
    { label: 'Completed', rows: items.filter((item) => item.status === 'done') },
  ];

  return <div className="h-full overflow-y-auto bg-background"><div className="mx-auto max-w-6xl px-5 py-8 sm:px-8 lg:py-10">
    <div className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Student workspace</p><h1 className="mt-2 flex items-center gap-3 text-3xl font-semibold"><CalendarClock className="size-7 text-primary" />Deadlines</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Application dates, requirement dates and your own milestones in one place. Dates you enter are your planning record until verified with the official source.</p></div><Button variant="outline" onClick={() => setVersion((value) => value + 1)}><RefreshCw className="mr-2 size-4" />Refresh</Button></div>
    {error && <p role="alert" className="mt-5 rounded-lg border border-destructive/30 p-3 text-sm text-destructive">{error}</p>}
    <div className="mt-7 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4"><div><p className="text-sm font-semibold">Viewing {range.start} to {range.end}</p><p className="text-xs text-muted-foreground">Move the window to see older or later dates.</p></div><div className="flex gap-2"><Button size="sm" variant="outline" aria-label="Earlier dates" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() - 6, 1))}><ChevronLeft className="size-4" /></Button><Button size="sm" variant="outline" onClick={() => setAnchor(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>Today</Button><Button size="sm" variant="outline" aria-label="Later dates" onClick={() => setAnchor(new Date(anchor.getFullYear(), anchor.getMonth() + 6, 1))}><ChevronRight className="size-4" /></Button></div></div>
    {loading ? <p className="mt-8 text-sm text-muted-foreground" role="status">Loading deadlines…</p> : <div className="mt-6 grid gap-5 lg:grid-cols-2">{groups.map((group) => <section key={group.label} className="rounded-2xl border bg-card p-5 shadow-sm"><h2 className="text-lg font-semibold">{group.label} <span className="ml-1 text-sm font-normal text-muted-foreground">{group.rows.length}</span></h2>{group.rows.length === 0 ? <p className="mt-4 text-sm text-muted-foreground">Nothing here in this date range.</p> : <div className="mt-4 space-y-3">{group.rows.map((item) => <div key={item.id} className="rounded-xl border p-3"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium">{item.title}</p><p className="mt-1 text-xs text-muted-foreground">{item.date} · {item.institution || item.category} · {item.source === 'personal' ? 'Your date' : item.source === 'application' ? 'Application' : 'Requirement'}</p></div><span className={`rounded-full px-2 py-0.5 text-[11px] ${group.label === 'Overdue' ? 'bg-destructive/10 text-destructive' : 'bg-muted text-muted-foreground'}`}>{item.status === 'done' ? 'Done' : group.label === 'Overdue' ? 'Overdue' : 'Open'}</span></div>{item.notes && <p className="mt-2 text-xs text-muted-foreground">{item.notes}</p>}{editing === item.source_id && item.source === 'personal' && <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); act(async () => { await workspaceApi.updateStudentDeadline(item.source_id, editDraft); setEditing(null); }); }}><input className={inputClass} aria-label="Edit deadline title" value={editDraft.title} required onChange={(event) => setEditDraft({ ...editDraft, title: event.target.value })} /><input className={inputClass} type="date" aria-label="Edit due date" value={editDraft.due_on} required onChange={(event) => setEditDraft({ ...editDraft, due_on: event.target.value })} /><Button type="submit" size="sm" disabled={busy}>Save</Button><Button type="button" size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button></form>}<div className="mt-3 flex flex-wrap gap-2">{item.application_id && <Button size="sm" variant="outline" onClick={() => openView('applications')}>Open application <ArrowRight className="ml-1 size-3.5" /></Button>}{safeSource(item.source_url) && <a className="inline-flex items-center rounded-md border px-3 py-1.5 text-xs hover:bg-muted" href={safeSource(item.source_url)!} target="_blank" rel="noopener noreferrer">Official source</a>}{item.source === 'personal' && <><Button size="sm" variant="ghost" disabled={busy} onClick={() => act(() => workspaceApi.updateStudentDeadline(item.source_id, { status: item.status === 'done' ? 'open' : 'done' }))}><Check className="mr-1 size-3.5" />{item.status === 'done' ? 'Reopen' : 'Done'}</Button><Button size="sm" variant="ghost" onClick={() => { setEditing(item.source_id); setEditDraft({ title: item.title, due_on: item.date }); }}>Edit</Button><Button size="sm" variant="ghost" disabled={busy} aria-label={`Delete ${item.title}`} onClick={() => act(() => workspaceApi.deleteStudentDeadline(item.source_id))}><Trash2 className="size-3.5" /></Button></>}</div></div>)}</div>}</section>)}</div>}
    <div className="mt-7 grid gap-5 lg:grid-cols-2"><section className="rounded-2xl border bg-card p-5"><h2 className="text-lg font-semibold">Add your own date</h2><p className="mt-1 text-xs text-muted-foreground">For scholarships, tests, visas or anything else. No institution requirements are assumed.</p><form className="mt-4 grid gap-3" onSubmit={(event) => { event.preventDefault(); act(async () => { await workspaceApi.createStudentDeadline({ ...draft, title: draft.title.trim(), category: draft.category.trim() || 'other', source_url: draft.source_url || null }); setDraft({ title: '', due_on: '', category: '', notes: '', source_url: '' }); }); }}><input className={inputClass} aria-label="Deadline title" placeholder="What is due?" value={draft.title} maxLength={240} required onChange={(event) => setDraft({ ...draft, title: event.target.value })} /><div className="grid gap-3 sm:grid-cols-2"><input className={inputClass} aria-label="Due date" type="date" value={draft.due_on} required onChange={(event) => setDraft({ ...draft, due_on: event.target.value })} /><input className={inputClass} aria-label="Category" placeholder="Category (optional)" value={draft.category} maxLength={80} onChange={(event) => setDraft({ ...draft, category: event.target.value })} /></div><input className={inputClass} aria-label="Official source URL" type="url" placeholder="Official source URL (optional)" value={draft.source_url} onChange={(event) => setDraft({ ...draft, source_url: event.target.value })} /><textarea className={inputClass} aria-label="Notes" placeholder="Notes (optional)" rows={2} maxLength={2000} value={draft.notes} onChange={(event) => setDraft({ ...draft, notes: event.target.value })} /><Button className="w-fit" type="submit" disabled={busy}><Plus className="mr-1 size-4" />Add deadline</Button></form></section>
    <section className="rounded-2xl border bg-card p-5"><h2 className="text-lg font-semibold">In-app reminders</h2><p className="mt-1 text-xs text-muted-foreground">Choose your calendar timezone and days before or after a deadline. Negative days mean overdue. Leave days empty to pause deadline reminders.</p><form className="mt-4 grid gap-3" onSubmit={(event) => { event.preventDefault(); const raw = daysDraft.trim(); const parts = raw ? raw.split(',').map((part) => part.trim()) : []; const values = parts.map(Number); if (parts.some((part) => !part) || values.some((value) => !Number.isInteger(value))) { setError('Enter whole reminder days separated by commas.'); return; } void act(() => workspaceApi.saveDeadlineSettings({ timezone: zoneDraft.trim(), reminder_days: values })); }}><label className="text-xs font-medium">Timezone<input className={inputClass + ' mt-1'} value={zoneDraft} onChange={(event) => setZoneDraft(event.target.value)} required /></label><Button className="w-fit" type="button" size="sm" variant="outline" onClick={() => setZoneDraft(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')}>Use my timezone</Button><label className="text-xs font-medium">Reminder days<input className={inputClass + ' mt-1'} value={daysDraft} placeholder="7, 1, 0, -1" onChange={(event) => setDaysDraft(event.target.value)} /></label><Button className="w-fit" type="submit" disabled={busy}>Save reminders</Button></form><p className="mt-4 text-xs text-muted-foreground">Reminders appear in Notifications. They do not email, submit an application or change an external account.</p></section></div>
  </div></div>;
}
