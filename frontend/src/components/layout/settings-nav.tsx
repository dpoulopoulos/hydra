import { NavLink } from 'react-router'

import { useAuth } from '@/hooks/use-auth'
import { cn } from '@/lib/utils'

/** The settings screens, with the admin one only where it applies. */
export function SettingsNav() {
  const { user } = useAuth()

  const items = [
    { to: '/settings/household', label: 'Household' },
    { to: '/settings/profile', label: 'Your profile' },
    { to: '/settings/api-tokens', label: 'API tokens' },
    ...(user?.is_superuser ? [{ to: '/settings/users', label: 'All users' }] : []),
  ]

  return (
    <nav className="flex gap-1 border-b" aria-label="Settings">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            cn(
              'border-b-2 px-3 py-2 text-sm font-medium transition-colors',
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
