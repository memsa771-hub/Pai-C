'use client';

import { CircleUser, FileText } from 'lucide-react';
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
  const { files } = useWorkspace();

  return [
    {
      label: t('nav.studentProfile'),
      items: [
        { mode: 'profile', label: t('views.profile'), icon: <CircleUser /> },
        { mode: 'files', label: t('views.files'), icon: <FileText />, count: countFiles(files) },
      ],
    },
  ];
}
