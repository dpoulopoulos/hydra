import { Settings } from 'lucide-react'
import { NavLink } from 'react-router'

import { Logo } from '@/components/layout/logo'
import { NAV_GROUPS } from '@/components/layout/nav'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { useAuth } from '@/hooks/use-auth'
import { usePendingBankCount } from '@/hooks/use-bank'
import { useHousehold } from '@/hooks/use-household'

export function AppSidebar() {
  const { data: household } = useHousehold()
  const { user } = useAuth()
  // The inbox fills from a bank or from a statement added through the API,
  // so it shows whether or not the server can connect a bank.
  const { data: pending = 0 } = usePendingBankCount()

  // Clients is for people paid by the session. It only shows for a user who
  // turned it on, so someone on a salary never meets it.
  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.clientsOnly || user?.clients_enabled),
  }))

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild>
              <NavLink to="/">
                <Logo />
                <div className="grid flex-1 text-left leading-tight">
                  <span className="truncate font-semibold">hydra</span>
                  <span className="text-muted-foreground truncate text-xs">
                    {household?.name ?? 'Loading…'}
                  </span>
                </div>
              </NavLink>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        {groups.map((group) => (
          <SidebarGroup key={group.label}>
            <SidebarGroupLabel>{group.label}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {group.items.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <NavLink to={item.to} end={item.to === '/'}>
                      {({ isActive }) => (
                        <SidebarMenuButton isActive={isActive} tooltip={item.label} asChild={false}>
                          <item.icon className="size-4" />
                          <span>{item.label}</span>
                        </SidebarMenuButton>
                      )}
                    </NavLink>
                    {item.to === '/inbox' && pending > 0 ? (
                      // Placed by hand: the badge finds its height through the
                      // button as a sibling, and here the link wraps the button.
                      <SidebarMenuBadge className="top-1.5">
                        {pending > 99 ? '99+' : pending}
                        <span className="sr-only"> to review</span>
                      </SidebarMenuBadge>
                    ) : null}
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>

      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <NavLink to="/settings">
              {({ isActive }) => (
                <SidebarMenuButton isActive={isActive} tooltip="Settings" asChild={false}>
                  <Settings className="size-4" />
                  <span>Settings</span>
                </SidebarMenuButton>
              )}
            </NavLink>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  )
}
