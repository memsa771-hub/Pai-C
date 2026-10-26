/** A question PAI or PAI OS asked the student (the student-requests contract). */
export interface StudentRequest {
  id: string;
  source: 'research' | 'os';
  execution_run_id: string | null;
  item_key: string;
  reason: string;
  accepts_upload: boolean;
  status: 'open' | 'answered' | 'withdrawn';
  created_at: string;
  asked_at: string | null;
  answered_at: string | null;
}
