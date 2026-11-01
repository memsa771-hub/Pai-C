'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { FileText, Flag, GraduationCap, Inbox, Package, PenLine, Plane, type LucideIcon } from 'lucide-react';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { OS_FROM_STAGE, OS_REHEARSAL_UI, OS_UI_ENABLED } from '@/lib/config';
import { useT } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** The PAI OS student pages, in menu order (the host sidebar's group and the OS pages' own header). */
export const OS_PAGES = [
  ['os-start', 'nav.osStart'],
  ['os-inbox', 'nav.osInbox'],
  ['os-documents', 'nav.osDocuments'],
  ['os-programmes', 'nav.osProgrammes'],
  ['os-statements', 'nav.osStatements'],
  ['os-pack', 'nav.osPack'],
  ['os-visa', 'nav.osVisa'],
] as const;

export type OsPage = (typeof OS_PAGES)[number][0];

const ICONS: Record<OsPage, LucideIcon> = {
  'os-start': Flag, 'os-inbox': Inbox, 'os-documents': FileText, 'os-programmes': GraduationCap,
  'os-statements': PenLine, 'os-pack': Package, 'os-visa': Plane,
};

/** Whether the study abroad plan is open to this student: from stage H ("Where to study", paths first and places
 * later), or at any stage in a rehearsal. `stageId` undefined (still loading) keeps it closed. */
export function osOpenAt(stageId: string | undefined, rehearsal = OS_REHEARSAL_UI): boolean {
  if (!OS_UI_ENABLED) return false;
  if (rehearsal) return true;
  return !!stageId && stageId >= OS_FROM_STAGE;
}

/** "Study abroad plan" in the counsellor's rail: the same pills, icons and current-page mark as the counsellor's own
 * places, so the two read as one app. Renders nothing until the plan is open to the student (osOpenAt). */
export function OsNavGroup({ stageId, current, collapsed = false, onNavigate }: {
  stageId?: string;
  /** The OS page shown now, marked as the current place. */
  current?: OsPage | null;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const workspaceId = useParams<{ workspaceId: string }>()?.workspaceId;  // null outside a workspace route
  const t = useT();
  if (!workspaceId || !osOpenAt(stageId)) return null;
  return (
    <div role="group" aria-label={t('nav.studyAbroadPlan')} className="pt-4">
      {!collapsed && (
        <p className="px-4 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {t('nav.studyAbroadPlan')}
        </p>
      )}
      <ul className="space-y-1">
        {OS_PAGES.map(([page, key]) => {
          const Icon = ICONS[page];
          const here = page === current;
          const link = (
            <Link href={`/${workspaceId}/${page}`} onClick={() => onNavigate?.()} aria-current={here ? 'page' : undefined}
              aria-label={collapsed ? t(key) : undefined}
              className={cn(
                'relative flex h-10 w-full items-center gap-3 rounded-full text-sm font-semibold transition-colors duration-200',
                collapsed ? 'justify-center' : 'px-4',
                here ? 'bg-primary text-primary-foreground shadow-[0_8px_18px_-8px_rgb(21_94_239/0.6)]'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}>
              <Icon aria-hidden className="size-[18px] shrink-0" strokeWidth={here ? 2.2 : 1.9} />
              {!collapsed && <span className="truncate">{t(key)}</span>}
            </Link>
          );
          return (
            <li key={page}>
              {collapsed ? (
                <Tooltip><TooltipTrigger asChild>{link}</TooltipTrigger><TooltipContent side="right">{t(key)}</TooltipContent></Tooltip>
              ) : link}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
