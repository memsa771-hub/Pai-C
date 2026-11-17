'use client';

import { useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Menu, X } from 'lucide-react';
import { PageHeader } from '@/components/pai';
import { ICONS, OS_PAGES, type OsPage } from '@/components/os/os-nav-group';
import { useMyPlan } from '@/components/os/my-plan-context';
import { useT } from '@/lib/i18n';

interface OsHeaderProps {
  workspaceId: string;
  /** The page this header is on: marked in the menu. */
  current: OsPage;
  /** The page's title, shown as its heading. */
  title: string;
  /** One line under the title, as on the counsellor's pages. */
  description?: string;
}

/** The OS pages' heading: the counsellor's own PageHeader (the "My plan" eyebrow, the page's icon, the
 * title), so both products read as one app. Desktop moves between the pages from the rail; on a phone the Menu
 * button opens the same links and the way back to the main menu (Slice 9 Task 11, `walk:S1:no_menu_on_os_pages`). */
export function OsHeader({ workspaceId, current, title, description }: OsHeaderProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { on, plan } = useMyPlan();
  const name = t(on ? 'nav.myPlan' : 'nav.myPlanOff');
  const pages = on && plan!.pages !== null ? plan!.pages.map((p) => [`os-${p.key}`, p.label] as const)
    : OS_PAGES.map(([page, key]) => [page, t(key)] as const);
  return (
    <>
      <PageHeader eyebrow={name} icon={ICONS[current]} title={title} description={description}
        className="mb-5 sm:mb-7"
        action={
          <button type="button" aria-expanded={open} aria-controls="os-menu" onClick={() => setOpen((o) => !o)}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-full border bg-card px-3.5 py-2 text-sm font-semibold shadow-xs lg:hidden">
            {open ? <X className="size-4" aria-hidden /> : <Menu className="size-4" aria-hidden />}
            Menu
          </button>
        } />
      {open && (
        <nav id="os-menu" aria-label={name} className="-mt-2 mb-5 rounded-2xl border bg-card p-2 text-sm shadow-card lg:hidden">
          <ul className="flex flex-col">
            {pages.map(([page, label]) => (
              <li key={page}>
                <Link href={`/${workspaceId}/${page}`} aria-current={page === current ? 'page' : undefined}
                      onClick={() => setOpen(false)}
                      className={`block rounded-full px-3.5 py-2 font-medium ${page === current ? 'bg-primary text-primary-foreground' : 'hover:bg-accent'}`}>
                  {label}
                </Link>
              </li>
            ))}
            <li className="mt-1 border-t pt-1">
              <Link href={`/${workspaceId}`} className="flex items-center gap-1.5 rounded-full px-3.5 py-2 text-muted-foreground hover:bg-accent">
                <ArrowLeft className="size-4" aria-hidden /> Back to the main menu
              </Link>
            </li>
          </ul>
        </nav>
      )}
    </>
  );
}
