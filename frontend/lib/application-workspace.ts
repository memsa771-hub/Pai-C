export interface Institution {
  id: string;
  name: string;
  country_code: string;
  city: string | null;
  website_url: string | null;
  source: string;
  provider: string | null;
  saved: boolean;
}

export type ApplicationStatus = 'planning' | 'preparing' | 'ready' | 'submitted' | 'decision' | 'withdrawn';
export type RequirementStatus = 'todo' | 'in_progress' | 'done' | 'not_applicable';

export interface ApplicationRequirement {
  id: string;
  label: string;
  kind: string;
  status: RequirementStatus;
  source_type: string;
  source_checked_at: string | null;
  due_at: string | null;
  source_url: string | null;
  notes: string | null;
  task_id: string | null;
  task_status: string | null;
  workflow_id: string | null;
  file_id: string | null;
  position: number;
}

export interface ApplicationPlan {
  id: string;
  institution: Institution;
  program_name: string | null;
  intake: string | null;
  route: string | null;
  status: ApplicationStatus;
  status_origin: string;
  deadline_at: string | null;
  application_url: string | null;
  notes: string | null;
  submitted_at: string | null;
  submission_reference: string | null;
  requirements: ApplicationRequirement[] | null;
  routines: ApplicationRoutine[] | null;
  created_at: string;
  updated_at: string;
}

export interface ApplicationRoutine {
  id: string;
  name: string;
  message: string;
  schedule_hour: number;
  schedule_minute: number;
  schedule_days: number[] | null;
  timezone: string;
  next_fires_at: string;
  status: string;
}

export interface ApplicationCalendarEvent {
  id: string;
  type: 'deadline' | 'requirement' | 'review';
  date: string;
  title: string;
  application_id: string;
  status: string;
}

export interface CreateInstitution {
  name: string;
  country_code: string;
  city?: string;
  website_url?: string;
}

export interface CreateApplication {
  institution_id: string;
  program_name?: string;
  intake?: string;
  route?: string;
  deadline_at?: string | null;
  application_url?: string | null;
  notes?: string | null;
}
