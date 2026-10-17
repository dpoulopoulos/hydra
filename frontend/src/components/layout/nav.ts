import {
  ArrowLeftRight,
  ChartColumnIncreasing,
  Flag,
  HandCoins,
  Inbox,
  LayoutDashboard,
  Repeat,
  Tags,
  Target,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from 'lucide-react'

/**
 * The screens of the app, in the groups the sidebar shows them in.
 *
 * Kept apart from the sidebar so the trail in the top bar can name the same
 * groups and screens without the two drifting apart.
 */
export type NavItem = {
  to: string
  label: string
  icon: LucideIcon
  /** Only for a user who turned clients on. */
  clientsOnly?: boolean
}

export type NavGroup = { label: string; items: NavItem[] }

export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Money',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/transactions', label: 'Transactions', icon: ArrowLeftRight },
      { to: '/inbox', label: 'Inbox', icon: Inbox },
      { to: '/accounts', label: 'Accounts', icon: Wallet },
      { to: '/clients', label: 'Clients', icon: HandCoins, clientsOnly: true },
      { to: '/investments', label: 'Investments', icon: TrendingUp },
    ],
  },
  {
    label: 'Planning',
    items: [
      { to: '/budgets', label: 'Budgets', icon: Target },
      { to: '/goals', label: 'Goals', icon: Flag },
      { to: '/recurring', label: 'Recurring', icon: Repeat },
      { to: '/categories', label: 'Categories', icon: Tags },
    ],
  },
  {
    label: 'Insight',
    items: [{ to: '/reports', label: 'Reports', icon: ChartColumnIncreasing }],
  },
]

/** The settings screens. The admin one is listed; who sees it is decided where it is shown. */
export const SETTINGS_PAGES = [
  { to: '/settings/household', label: 'Household' },
  { to: '/settings/profile', label: 'Your profile' },
  { to: '/settings/api-tokens', label: 'API tokens' },
  { to: '/settings/bank', label: 'Banks' },
  { to: '/settings/users', label: 'All users', adminOnly: true },
]
