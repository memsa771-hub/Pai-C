'use client';

import { FileList } from '@/components/files/file-list';
import { BrowserTabList } from '@/components/browser/browser-tab-list';
import { useLayout } from './layout-context';

/**
 * The app-shell-4 second inner sidebar: a wide list panel that fills whatever
 * space the sidebar has left over after the icon rail. Each list owns its own
 * `--header-height` header, so it lines up with the rail and the detail header.
 */
export function ListPanel() {
  const { viewMode } = useLayout();

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-background">
      {viewMode === 'files' && <FileList />}
      {viewMode === 'browser' && <BrowserTabList />}
    </div>
  );
}
