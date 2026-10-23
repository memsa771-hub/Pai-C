/**
 * PAI OS replanning: types and pure helpers. Data comes from GET /v1/os/changes, the proposal answers and the admin
 * support inbox (backend/app/os/api/replan.py, Slice 7 spec §4-5). Kept free of React. Nothing here knows a route:
 * steps are named from their keys, programmes from the names the page passes in.
 */

type Why = { reason: string };
export type OsReplanOp =
  | ({ op: 'add_task'; template_key: string; programme_ref: string | null } & Why)
  | ({ op: 'skip_task'; instance_key: string } & Why)
  | ({ op: 'cancel_task'; instance_key: string } & Why)
  | ({ op: 'cancel_programme'; programme_ref: string } & Why)
  | ({ op: 'reprioritise'; instance_key: string; before: string } & Why)
  | ({ op: 'swap_programme'; out_ref: string; in_ref: string } & Why)
  | ({ op: 'request_from_student'; instance_key: string; message: string } & Why)
  | ({ op: 'escalate' } & Why)
  | ({ op: 'upgrade_playbook'; version: number } & Why);

export interface OsProposal {
  id: number;
  plan_id: number;
  status: 'applied' | 'pending' | 'accepted' | 'declined' | 'expired' | 'refused';
  big: boolean;
  source: 'rules' | 'supervisor';
  ops: OsReplanOp[];
  reasons: string[];
  revision: number | null;
  expires_at: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface OsChange extends OsProposal {
  proposal_id: number;
  at: string;
}

export interface OsChanges {
  plan_id: number;
  changes: OsChange[];
  pending: OsProposal[];
  changes_paused: boolean;
}

export interface OsSupportCase {
  id: number;
  plan_id: number;
  student_ref: string;
  reason: string;
  event_ids: number[];
  proposal_id: number | null;
  status: 'open' | 'resolved';
  resolution: string | null;
  created_at: string;
  resolved_at: string | null;
  changes_paused: boolean;
}

/** "review_visa_file#2" -> "Review visa file"; "apply@prog-a" -> "Apply". */
export function stepName(key: string): string {
  const base = key.split('@')[0].split('#')[0].replace(/_/g, ' ').trim();
  return base.charAt(0).toUpperCase() + base.slice(1);
}

function programmeOf(key: string): string | null {
  const at = key.indexOf('@');
  return at < 0 ? null : key.slice(at + 1).split('#')[0];
}

/** One operation in words for the student. */
export function opText(op: OsReplanOp, names: Record<string, string> = {}): string {
  const name = (ref: string) => names[ref] ?? ref;
  const step = (key: string) => {
    const ref = programmeOf(key);
    return `“${stepName(key)}”${ref ? ` for ${name(ref)}` : ''}`;
  };
  switch (op.op) {
    case 'add_task': return `Add the step “${stepName(op.template_key)}”${op.programme_ref ? ` for ${name(op.programme_ref)}` : ''}`;
    case 'skip_task': return `Skip ${step(op.instance_key)}`;
    case 'cancel_task': return `Remove ${step(op.instance_key)}`;
    case 'cancel_programme': return `Remove the steps for ${name(op.programme_ref)}`;
    case 'reprioritise': return `Do ${step(op.instance_key)} before ${step(op.before)}`;
    case 'swap_programme': return `Replace ${name(op.out_ref)} with ${name(op.in_ref)}`;
    case 'request_from_student': return op.message;
    case 'escalate': return 'Ask a person to check your plan';
    case 'upgrade_playbook': return `Move your plan to the newest guide (version ${op.version})`;
  }
}

export function answerBy(p: OsProposal): string | null {
  return p.expires_at ? new Date(p.expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : null;
}

export function newestFirst(changes: OsChange[]): OsChange[] {
  return [...changes].sort((a, b) => b.at.localeCompare(a.at));
}
