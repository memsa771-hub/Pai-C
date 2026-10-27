'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarMenu, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar';
import { OS_UI_ENABLED } from '@/lib/config';
import { useT } from '@/lib/i18n';

const PAGES = [
  ['os-start', 'nav.osStart'],
  ['os-inbox', 'nav.osInbox'],
  ['os-documents', 'nav.osDocuments'],
  ['os-programmes', 'nav.osProgrammes'],
  ['os-statements', 'nav.osStatements'],
  ['os-pack', 'nav.osPack'],
  ['os-visa', 'nav.osVisa'],
] as const;

/** "Study abroad plan" menu group: links to the PAI OS pages. Renders nothing unless NEXT_PUBLIC_OS_ENABLED=true. */
export function OsNavGroup({ onNavigate }: { onNavigate?: () => void }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const t = useT();
  if (!OS_UI_ENABLED || !workspaceId) return null;
  return <SidebarGroup>
    <SidebarGroupLabel>{t('nav.studyAbroadPlan')}</SidebarGroupLabel>
    <SidebarGroupContent><SidebarMenu className="gap-0.5">
      {PAGES.map(([page, key]) => <SidebarMenuItem key={page}>
        <SidebarMenuButton asChild tooltip={t(key)}>
          <Link href={`/${workspaceId}/${page}`} onClick={() => onNavigate?.()}><span>{t(key)}</span></Link>
        </SidebarMenuButton>
      </SidebarMenuItem>)}
    </SidebarMenu></SidebarGroupContent>
  </SidebarGroup>;
}
