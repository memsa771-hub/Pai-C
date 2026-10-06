'use client';

import { CalendarClock, CircleUser, FileText, Globe, GraduationCap, KanbanSquare, Waypoints } from 'lucide-react';
import { TASKS_UI_ENABLED, WORKFLOWS_UI_ENABLED } from '@/lib/config';
import { countFiles } from '@/components/files/file-utils';
import { useT } from '@/lib/i18n';
import { useWorkspace } from '@/lib/workspace-context';
import type { ViewMode } from './layout-context';

export interface WorkspaceNavItem {
  mode: ViewMode;
  label: string;
  icon: React.ReactNode;
  count?: number;
  urgent?: boolean;
}

export interface WorkspaceNavGroup {
  label: string;
  items: WorkspaceNavItem[];
}

/** One information architecture for the desktop rail and mobile drawer. */
export function useWorkspaceNavigation(): WorkspaceNavGroup[] {
  const t = useT();
  const { files, browserTabs, tasks, workflows } = useWorkspace();

  return [
    {
      label: t('nav.studentProfile'),
      items: [
        { mode: 'profile', label: t('views.profile'), icon: <CircleUser /> },
        { mode: 'files', label: t('views.files'), icon: <FileText />, count: countFiles(files) },
      ],
    },
    {
      label: t('nav.applicationWorkspace'),
      items: [
        { mode: 'applications', label: t('views.applications'), icon: <GraduationCap /> },
        { mode: 'deadlines', label: t('views.deadlines'), icon: <CalendarClock /> },
        ...(TASKS_UI_ENABLED ? [{
          mode: 'tasks' as const, label: t('views.tasks'), icon: <KanbanSquare />,
          count: tasks.filter((task) => task.status === 'need_input').length, urgent: true,
        }] : []),
        ...(WORKFLOWS_UI_ENABLED ? [{
          mode: 'workflows' as const, label: t('views.workflows'), icon: <Waypoints />,
          count: workflows.length,
        }] : []),
      ],
    },
    {
      label: t('nav.tools'),
      items: [{ mode: 'browser', label: t('views.browser'), icon: <Globe />, count: browserTabs.length }],
    },
  ];
}
