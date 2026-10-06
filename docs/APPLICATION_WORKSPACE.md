# Application Workspace

Code layout: [backend package](../backend/app/application_workspace/README.md),
[frontend application views](../frontend/components/applications) and
[deadline views](../frontend/components/deadlines). The top-level router file
is a small registration shim; planning logic lives in the backend package.

The Application Workspace is a student-owned operational surface. It is separate
from Profile/Vault: an application plan describes work the student intends to do;
it is not automatically a verified fact about an admission or a submission.

## Navigation

PAI Counselor is the primary conversation entry. PAI OS groups the student-owned
surfaces by purpose: **Student profile** (Profile, Documents), **Application
workspace** (Applications, Deadlines, plus Tasks/Workflows when enabled), and
**Tools** (Research Browser). The notification bell remains global. Desktop
and mobile navigation use the same group definitions; mobile quick tabs lead
to Counselor, Profile and Applications. These labels describe existing
capabilities, not separate data stores or a second counselor.

This follows the distinction in [Common App's student navigation](https://www.commonapp.org/files/Common-App-UI-updates.pdf)
between an application's shared information, institution-specific work and
exploration. [UCAS Hub](https://www.ucas.com/applying) similarly keeps exploring,
applying and tracking choices within one student journey. PAI adds a persistent
Counselor and reusable student profile across application plans.

## Current flow

1. Search visible institutions. Trusted catalog entries (when connected later)
   are global; student-added entries are private to their workspace.
2. Add a missing institution with name and country, then save it. Search results
   never pretend that a student-added institution is verified.
3. Create one plan per institution/program/intake. Track route, deadline,
   application URL, notes, self-reported status and submission reference.
4. Add per-plan requirements from official sources. Each requirement can have a
   type, due date, source URL, completion state, linked workspace task and file.
   The UI creates a standard Kanban task atomically with its requirement link.
   The student can attach an existing workflow template, build a new template,
   run it explicitly and open the ordinary task conversation. A task is never
   silently assigned or run. A completed linked task satisfies its requirement
   in the application read model.
5. The application calendar reads plan deadlines, requirement due dates and
   the next scheduled recurring review from one scoped endpoint. Dates are
   student-entered until a partner verifies them.
6. A student can opt into recurring PAI application reviews in their IANA time
   zone. These are existing scheduler routines linked to the application;
   cancelling a review stops the scheduler row. The schedule handles daylight
   saving transitions. The routine asks PAI to review and discuss the plan;
   it does not submit or change external applications.
7. The top-level **Deadlines** view combines application deadlines, requirement
   dates and student-created dates into one workspace read model. Dates are
   stored once at their source, so editing an application updates the central
   list without a second calendar record. The view groups overdue, near-term,
   later and completed work. Student-created dates can cover scholarships,
   tests, visas or other milestones without a fixed country checklist.
8. The top-level **Notifications** view uses the existing durable workspace
   inbox for agent/work updates and system deadline reminders. The student
   chooses an IANA timezone and reminder offsets (including negative offsets
   for overdue dates); an empty list pauses reminders. A database uniqueness
   key prevents duplicate notices when scheduler replicas overlap. Changed
   or completed dates expire stale notices. The visible workspace refreshes
   the notification badge periodically. Reminders are in-app only.

No endpoint submits an application or changes university data. The UI labels
submitted status as the student's own record. There is no seeded college list,
country-specific checklist, fabricated deadline or assumed application route.

## Integration seam

`pai_institutions` owns stable catalog identity. A provider can upsert a public
entry by `(provider, provider_id)` and attach its official website. Private
student entries should be reconciled with trusted entries via a reviewed merge
that preserves existing plan IDs; merely matching names is insufficient to
merge. A production catalog import should validate source rights, provenance,
country, canonical URLs and update dates before publishing entries.

`pai_application_plans` owns student progress. `status_origin` distinguishes
student updates from later verified partner updates. `external_provider` and
`external_id` are reserved for a future partner adapter. Submission requires
a separate approval and receipt flow; a self-reported `submitted` status is
not evidence of a partner submission. Partner requirements should retain
source, cycle and freshness; this schema stores a source URL, source type and
source check time on each requirement. Student-created requirements do not
claim verification.

`pai_application_requirements.task_id` links to the existing Kanban board,
`file_id` to the existing workspace file store, and the linked task's
`workflow_id` references the existing workflow template. A separate
`pai_application_routines` relation links existing scheduler routines to a
plan. The application workspace coordinates these systems using stable IDs;
it does not fork their execution engines. External submissions and other
consequential partner writes still need a separate student approval flow.

The application workspace does not write directly to canonical Vault records.
When admission outcomes are later reconciled into Student Understanding, they
must use the existing candidate → reconciliation path with evidence and origin.

## Deployment

Run Alembic migrations `079_application_workspace` and `080_student_deadlines`
with the normal backend migration service before starting the updated API.
No new environment variables are required.

## Student OS feature inventory

| Surface | Current capability | Boundary for future agent work |
| --- | --- | --- |
| Profile / Vault | Reusable student understanding and documents | App work never silently becomes a verified profile fact |
| PAI Counselor | Shared text/voice counseling and student context | Agent planning can read work context without owning external submissions |
| Applications | Saved institutions, per-program plans, sourced requirements, progress | Partner catalog and submission adapters attach to stable IDs |
| Tasks / Workflows | Application requirements link to standard task/workflow engine | Runs require an explicit student action and existing workflow gates |
| Routines | Student-scheduled PAI application reviews | No unsupervised institution writes |
| Deadlines | Unified application, requirement and personal dates | Future sources can add a scoped read adapter; no copied dates |
| Notifications | Existing bottom bell opens a quick preview and the same durable inbox via View all; deadline reminders use the shared notification service | Future channels need consent, delivery preferences and auditability |
| Files | Attach existing workspace documents to requirements | Partner upload remains a separate approved action |

Not yet implemented: a licensed global institution catalog, live official
requirement sync, external admissions submission, email/SMS/push delivery,
cross-system calendar sync, or autonomous agent submission. Student-entered
dates and statuses must be checked against their official source before use.
The central reminder system currently works at the calendar-day level;
time-specific cutoffs need an explicit institution timezone and verified
source before PAI can promise hour-accurate alerts.
Standalone Kanban tasks have no due-date field yet; an application-linked
task uses its requirement's due date in the central list.

Research basis: [UCAS application dates](https://www.ucas.com/applying/applying-to-university/dates-and-deadlines-for-uni-applications)
vary by course and sometimes school process; the
[Common App requirements grid](https://content.commonapp.org/Files/ReqGrid.pdf)
shows institution-specific deadlines and requirements. This is why PAI stores
per-plan sources and does not seed a single universal checklist. The
[W3C guidance for status messages](https://www.w3.org/WAI/WCAG21/Understanding/status-messages)
informs the visible loading/error states and separate notification center.
