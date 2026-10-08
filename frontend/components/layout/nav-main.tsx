'use client';

import { Badge } from '@/components/ui/badge';
import { SidebarGroup, SidebarGroupContent, SidebarGroupLabel, SidebarMenu, SidebarMenuBadge, SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar';
import { AgentAvatar } from '@/components/agents/agent-avatar';
import { useWorkspace } from '@/lib/workspace-context';
import { useT } from '@/lib/i18n';
import { PAI_PRIMARY_CONVERSATION_ID } from '@/lib/primary-conversation';
import { Map } from 'lucide-react';
import { useLayout } from './layout-context';
import { useWorkspaceNavigation } from './workspace-navigation';

/** Full navigation for the mobile drawer. */
export function NavMain({ onNavigate }: { onNavigate?: () => void }) {
  const { viewMode, openView, openMobileDetail, setSelectedAgentName } = useLayout();
  const { setCurrentSessionId } = useWorkspace();
  const groups = useWorkspaceNavigation();
  const t = useT();

  const openPaiCounselor = () => {
    setCurrentSessionId(PAI_PRIMARY_CONVERSATION_ID);
    openView('threads');
    openMobileDetail();
    setSelectedAgentName(null);
    onNavigate?.();
  };

  return <>
    <SidebarGroup>
      <SidebarGroupLabel>{t('nav.guide')}</SidebarGroupLabel>
      <SidebarGroupContent><SidebarMenu><SidebarMenuItem>
        <SidebarMenuButton tooltip={t('views.paiCounselor')} isActive={viewMode === 'threads'} onClick={openPaiCounselor}>
          <AgentAvatar name="pai" size={16} className="[&_svg]:size-full!" />
          <span>{t('views.paiCounselor')}</span>
        </SidebarMenuButton>
      </SidebarMenuItem><SidebarMenuItem>
        <SidebarMenuButton tooltip={t('views.roadmaps')} isActive={viewMode === 'roadmaps'} onClick={() => { openView('roadmaps'); onNavigate?.(); }}>
          <Map className="size-4" /><span>{t('views.roadmaps')}</span>
        </SidebarMenuButton>
      </SidebarMenuItem></SidebarMenu></SidebarGroupContent>
    </SidebarGroup>
    <div className="px-4 pt-4 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground">{t('nav.paiOs')}</div>
    {groups.map((group) => <SidebarGroup key={group.label}>
      <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
      <SidebarGroupContent><SidebarMenu className="gap-0.5">
        {group.items.map((item) => <SidebarMenuItem key={item.mode}>
          <SidebarMenuButton tooltip={item.label} isActive={viewMode === item.mode} onClick={() => { openView(item.mode); onNavigate?.(); }}>
            {item.icon}<span>{item.label}</span>
          </SidebarMenuButton>
          {item.count !== undefined && item.count > 0 && <SidebarMenuBadge>
            <Badge variant={item.urgent ? 'destructive' : 'secondary'} appearance="light" size="sm" shape="circle" className="min-w-5 justify-center px-1.5 tabular-nums">{item.count}</Badge>
          </SidebarMenuBadge>}
        </SidebarMenuItem>)}
      </SidebarMenu></SidebarGroupContent>
    </SidebarGroup>)}
  </>;
}
