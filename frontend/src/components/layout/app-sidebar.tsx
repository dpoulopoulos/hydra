import {
  ArrowLeftRight,
  ChartColumnIncreasing,
  Flag,
  HandCoins,
  Inbox,
  LayoutDashboard,
  Repeat,
  Settings,
  Tags,
  Target,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import { NavLink } from 'react-router'

import { Logo } from '@/components/layout/logo'
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
import { useBankStatus, usePendingBankCount } from '@/hooks/use-bank'
import { useHousehold } from '@/hooks/use-household'

const money = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/transactions', label: 'Transactions', icon: ArrowLeftRight },
  // Only where the server can connect a bank: see `bankOnly` below.
  { to: '/inbox', label: 'Inbox', icon: Inbox, bankOnly: true },
  { to: '/accounts', label: 'Accounts', icon: Wallet },
  // Only for a user who turned it on: see `clientsOnly` below.
  { to: '/clients', label: 'Clients', icon: HandCoins, clientsOnly: true },
  { to: '/investments', label: 'Investments', icon: TrendingUp },
]

const planning = [
  { to: '/budgets', label: 'Budgets', icon: Target },
  { to: '/goals', label: 'Goals', icon: Flag },
  { to: '/recurring', label: 'Recurring', icon: Repeat },
  { to: '/categories', label: 'Categories', icon: Tags },
]

const insight = [{ to: '/reports', label: 'Reports', icon: ChartColumnIncreasing }]

export function AppSidebar() {
  const { data: household } = useHousehold()
  const { user } = useAuth()
  const bankEnabled = useBankStatus().data?.enabled ?? false
  const { data: pending = 0 } = usePendingBankCount({ enabled: bankEnabled })

  // Clients is for people paid by the session. It only shows for a user who
  // turned it on, so someone on a salary never meets it. The inbox only fills
  // from a bank, so a server that cannot connect one does not show it.
  const moneyItems = money.filter(
    (item) => (!item.clientsOnly || user?.clients_enabled) && (!item.bankOnly || bankEnabled),
  )

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
        {[
          { label: 'Money', items: moneyItems },
          { label: 'Planning', items: planning },
          { label: 'Insight', items: insight },
        ].map((group) => (
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
