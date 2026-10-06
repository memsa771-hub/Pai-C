'use client';

import { useCallback, useEffect, useState } from 'react';
import { ArrowRight, Clock3, ListTodo, Plus, RefreshCw, Workflow as WorkflowIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { WorkflowBuilderDialog } from '@/components/workflows/workflow-builder-dialog';
import { TaskChatPopup } from '@/components/tasks/task-chat-popup';
import { workspaceApi } from '@/lib/api';
import type { ApplicationPlan } from '@/lib/application-workspace';
import type { KanbanTask, Workflow } from '@/lib/types';

const inputClass = 'w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/15';

export function ApplicationOperations({ plan, onRefresh }: { plan: ApplicationPlan; onRefresh: () => Promise<void> }) {
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [builderOpen, setBuilderOpen] = useState(false);
  const [chatTask, setChatTask] = useState<KanbanTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [routineName, setRoutineName] = useState('');
  const [routineMessage, setRoutineMessage] = useState('');
  const [routineTime, setRoutineTime] = useState('09:00');
  const [routineDays, setRoutineDays] = useState<number[]>([]);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const monday = new Date();
  monday.setUTCDate(monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7));

  const loadWork = useCallback(async () => {
    const [taskResult, workflowResult] = await Promise.all([workspaceApi.listTasks(), workspaceApi.listWorkflows()]);
    setTasks(taskResult.tasks);
    setWorkflows(workflowResult.workflows);
  }, []);
  useEffect(() => {
    let live = true;
    Promise.all([workspaceApi.listTasks(), workspaceApi.listWorkflows()])
      .then(([taskResult, workflowResult]) => { if (live) { setTasks(taskResult.tasks); setWorkflows(workflowResult.workflows); } })
      .catch(() => { if (live) setError('Could not load tasks or workflows.'); });
    return () => { live = false; };
  }, [plan.id, plan.requirements?.map((item) => item.task_id).join(',')]);

  async function act(action: () => Promise<unknown>) {
    setBusy(true); setError('');
    try { await action(); await Promise.all([loadWork(), onRefresh()]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Could not update application work.'); }
    finally { setBusy(false); }
  }

  const linked = (plan.requirements || []).filter((item) => item.task_id);
  return <>
    <section className="mt-6 rounded-2xl border bg-card p-5 shadow-sm sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="flex items-center gap-2 text-xl font-semibold"><ListTodo className="size-5 text-primary" />Tasks & workflows</h3><p className="mt-1 text-sm text-muted-foreground">One task per requirement. Choose a workflow template if agents should work through its steps.</p></div><Button variant="outline" size="sm" onClick={() => setBuilderOpen(true)}><Plus className="mr-1 size-4" />New workflow</Button></div>
      {error && <p role="alert" className="mt-4 text-sm text-destructive">{error}</p>}
      {(plan.requirements || []).length === 0 ? <p className="mt-5 rounded-xl border border-dashed p-5 text-sm text-muted-foreground">Add a requirement above to create work for it.</p> : <div className="mt-5 space-y-3">{(plan.requirements || []).map((item) => { const task = tasks.find((candidate) => candidate.id === item.task_id); return <div key={item.id} className="rounded-xl border p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium">{item.label}</p><p className="mt-1 text-xs text-muted-foreground">{task ? `Task: ${task.status.replace('_', ' ')}` : 'Student checklist item · no task yet'}</p></div>{!item.task_id && <Button size="sm" disabled={busy} onClick={() => act(() => workspaceApi.ensureApplicationTask(plan.id, item.id))}>Create task</Button>}</div>{item.task_id && <div className="mt-3 flex flex-wrap items-center gap-2"><select className={inputClass + ' max-w-56'} aria-label={`Workflow for ${item.label}`} value={item.workflow_id || ''} disabled={busy || task?.status === 'in_progress'} onChange={(event) => act(() => workspaceApi.ensureApplicationTask(plan.id, item.id, event.target.value))}><option value="">Manual task</option>{workflows.map((workflow) => <option key={workflow.id} value={workflow.id}>{workflow.name}</option>)}</select>{task?.workflowId && task.status !== 'in_progress' && task.status !== 'done' && <Button size="sm" disabled={busy} onClick={() => act(() => workspaceApi.assignTask(task.id))}>Run workflow <ArrowRight className="ml-1 size-3.5" /></Button>}{task?.channelName && <Button size="sm" variant="outline" onClick={() => setChatTask(task)}>Open work chat</Button>}{task?.status === 'need_input' && <span className="text-xs font-medium text-amber-700">PAI needs your input</span>}</div>}</div>; })}</div>}
      {linked.length > 0 && <Button className="mt-4" size="sm" variant="ghost" disabled={busy} onClick={() => act(async () => {})}><RefreshCw className="mr-1 size-3.5" />Refresh task progress</Button>}
      <p className="mt-4 text-xs text-muted-foreground">Creating a task does not run it. Running a workflow uses the existing agent task system; submission still requires a separate approved integration.</p>
    </section>
    <section className="mt-6 rounded-2xl border bg-card p-5 shadow-sm sm:p-7">
      <h3 className="flex items-center gap-2 text-xl font-semibold"><Clock3 className="size-5 text-primary" />Recurring PAI reviews</h3><p className="mt-1 text-sm text-muted-foreground">Schedule a conversation about this application. Dates and one-time deadlines appear in the calendar above.</p>
      {(plan.routines || []).filter((routine) => routine.status === 'active').map((routine) => <div key={routine.id} className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3"><div><p className="text-sm font-medium">{routine.name}</p><p className="text-xs text-muted-foreground">Next {new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: routine.timezone }).format(new Date(routine.next_fires_at))} · {routine.timezone}</p></div><Button size="sm" variant="outline" disabled={busy} onClick={() => act(() => workspaceApi.cancelApplicationRoutine(plan.id, routine.id))}>Stop review</Button></div>)}
      <form className="mt-5 grid gap-3 border-t pt-5 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); const [hour, minute] = routineTime.split(':').map(Number); act(async () => { await workspaceApi.createApplicationRoutine(plan.id, { name: routineName.trim(), message: routineMessage.trim(), hour, minute, days: routineDays.length ? routineDays : null, timezone }); setRoutineName(''); setRoutineMessage(''); }); }}><input className={inputClass} required maxLength={160} placeholder="Review name" aria-label="Review name" value={routineName} onChange={(event) => setRoutineName(event.target.value)} /><input className={inputClass} required maxLength={1000} placeholder="What should PAI review with you?" aria-label="Review instruction" value={routineMessage} onChange={(event) => setRoutineMessage(event.target.value)} /><label className="text-xs text-muted-foreground">Time in {timezone}<input className={inputClass + ' mt-1'} type="time" value={routineTime} required onChange={(event) => setRoutineTime(event.target.value)} /></label><div className="flex flex-wrap items-end gap-1" aria-label="Review weekdays">{[0, 1, 2, 3, 4, 5, 6].map((day) => { const date = new Date(monday); date.setUTCDate(monday.getUTCDate() + day); const label = new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(date); const active = routineDays.includes(day); return <button key={day} type="button" aria-pressed={active} title={label} className={`rounded-md border px-2 py-2 text-xs ${active ? 'border-primary bg-primary/10 text-primary' : 'text-muted-foreground'}`} onClick={() => setRoutineDays(active ? routineDays.filter((value) => value !== day) : [...routineDays, day])}>{label}</button>; })}<span className="w-full text-xs text-muted-foreground">No days selected = every day</span></div><Button type="submit" className="sm:col-span-2 sm:w-fit" disabled={busy || !routineName.trim() || !routineMessage.trim()}>Schedule review</Button></form>
    </section>
    <WorkflowBuilderDialog open={builderOpen} onOpenChange={setBuilderOpen} workflow={null} onSave={(input) => { act(async () => { await workspaceApi.createWorkflow(input); setBuilderOpen(false); }); }} />
    {chatTask?.channelName && <TaskChatPopup open={!!chatTask} onOpenChange={(open) => !open && setChatTask(null)} sessionId={chatTask.channelName} taskTitle={chatTask.title} assignee={chatTask.assignee} />}
  </>;
}
