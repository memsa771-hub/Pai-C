/** Report a fact as wrong (P2-T7, R-28). Every sentence the student sees comes from the server (approved copy in
 * monitor/texts.yaml); nothing here words it. A 429 means the day's limit, anything else a failed send. */

export interface OsReportTexts {
  reasons: Array<{ code: string; label: string }>;
  texts: Record<'report_link' | 'report_title' | 'report_detail_label' | 'report_submit' | 'report_thanks' | 'report_limit'
    | 'report_failed', string>;
}

/** The sentence for the outcome of sending a report. */
export function reportOutcome(texts: OsReportTexts['texts'], error: unknown): string {
  const status = (error as { status?: number } | null)?.status ?? (error instanceof Error ? Number(/^API (\d+)/.exec(error.message)?.[1]) : NaN);
  if (error == null) return texts.report_thanks;
  return status === 429 ? texts.report_limit : texts.report_failed;
}

/** Whether the answer has the shape of the texts; anything else reads as "reporting is off". */
export function asReportTexts(body: unknown): OsReportTexts | null {
  const b = body as Partial<OsReportTexts> | null;
  if (!b || !Array.isArray(b.reasons) || !b.reasons.length || !b.texts || typeof b.texts.report_link !== 'string') return null;
  return b as OsReportTexts;
}
