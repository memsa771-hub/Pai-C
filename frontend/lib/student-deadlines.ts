export interface StudentDeadline {
  id: string;
  source: 'personal' | 'application' | 'requirement';
  source_id: string;
  application_id: string | null;
  title: string;
  date: string;
  status: 'open' | 'done';
  category: string;
  source_url: string | null;
  notes: string | null;
  institution: string | null;
}

export interface DeadlineSettings {
  timezone: string;
  reminder_days: number[];
}
