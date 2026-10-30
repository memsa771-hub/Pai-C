'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Menu, X } from 'lucide-react';
import { OS_PAGES } from '@/components/os/os-nav-group';
import { useT } from '@/lib/i18n';

type OsPage = (typeof OS_PAGES)[number][0];

interface OsHeaderProps {
  workspaceId: string;
  /** The page this header is on: marked in the menu. */
  current: OsPage;
  /** The page's title, shown as its heading. */
  title: string;
}

/** The OS pages' own header (Slice 9 Task 11, `walk:S1:no_menu_on_os_pages`): mobile-first, the page title and a
 * Menu button that opens the links to the other study abroad plan pages and back to the workspace home. */
export function OsHeader({ workspaceId, current, title }: OsHeaderProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  return (
    <header className="mb-4">
      <div className="flex items-center gap-2">
        <h1 className="min-w-0 flex-1 break-words text-lg font-semibold">{title}</h1>
        <button type="button" aria-expanded={open} aria-controls="os-menu" onClick={() => setOpen((o) => !o)}
                className="inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1.5 text-sm">
          {open ? <X className="size-4" aria-hidden /> : <Menu className="size-4" aria-hidden />}
          Menu
        </button>
      </div>
      {open && (
        <nav id="os-menu" aria-label={t('nav.studyAbroadPlan')} className="mt-2 rounded-lg border bg-card p-2 text-sm">
          <ul className="flex flex-col">
            {OS_PAGES.map(([page, key]) => (
              <li key={page}>
                <Link href={`/${workspaceId}/${page}`} aria-current={page === current ? 'page' : undefined}
                      onClick={() => setOpen(false)}
                      className={`block rounded-md px-2 py-2 ${page === current ? 'bg-muted font-medium' : ''}`}>
                  {t(key)}
                </Link>
              </li>
            ))}
            <li className="mt-1 border-t pt-1">
              <Link href={`/${workspaceId}`} className="flex items-center gap-1 rounded-md px-2 py-2 text-muted-foreground">
                <ArrowLeft className="size-4" aria-hidden /> Back to the main menu
              </Link>
            </li>
          </ul>
        </nav>
      )}
    </header>
  );
}
