import { NavLink } from 'react-router'

import { SETTINGS_PAGES } from '@/components/layout/nav'
import { useAuth } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'

/** The settings screens, with the admin one only where it applies. */
export function SettingsNav() {
  const { user } = useAuth()

  const items = SETTINGS_PAGES.filter((item) => !item.adminOnly || user?.is_superuser)

  return (
    // Scrolls on its own where the tabs do not fit, so a phone neither wraps
    // them onto two lines nor scrolls the whole page sideways.
    <nav
      className="-mx-4 flex scrollbar-none gap-1 overflow-x-auto border-b px-4 md:mx-0 md:px-0"
      aria-label="Settings"
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              'border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap transition-colors',
              isActive
                ? 'border-primary text-foreground'
                : 'text-muted-foreground hover:text-foreground border-transparent',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
