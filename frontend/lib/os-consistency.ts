/** PAI OS admin: consistency cases (P1-T10, R-05). The nightly check of the Counsellor and PAI OS opens one case per
 * student and rule; a person resolves it. Staff words, not student sentences. A case holds a rule number and codes only. */

export interface OsConsistencyCase {
  id: number;
  student_ref: string;
  rule: number;
  plan_id: number | null;
  codes: string[];
  status: 'open' | 'resolved';
  resolution: string | null;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
}

/** What each rule of the check compares (master 9.3). */
export const RULE_LABELS: Record<number, string> = {
  1: 'Choice and plan',
  2: 'Plan and decision',
  3: 'Withdrawn choice and plan',
  4: 'Checklist and roadmap',
  5: 'Vault and replan',
  6: 'Files',
  7: 'Duplicate requests',
  8: 'Excluded fields',
};

export function ruleLabel(rule: number): string {
  return RULE_LABELS[rule] ?? `Rule ${rule}`;
}

/** "contract_hash" -> "contract hash". */
export function codeLabel(code: string): string {
  return code.replace(/_/g, ' ');
}

/** The endpoint answers 404 when the check is not part of this deployment: the list is then hidden. */
export function isMissingEndpoint(error: unknown): boolean {
  return error instanceof Error && error.message.startsWith('API 404');
}
