import { House, LogOut, User as UserIcon } from 'lucide-react'
import { useNavigate } from 'react-router'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAuth } from '@/hooks/use-auth'

/** The first letters of a name, or of an email when there is no name. */
function initials(name: string | null | undefined, email: string): string {
  const source = name?.trim() || email
  const parts = source.split(/[\s@.]+/).filter(Boolean)
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function UserMenu() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  if (!user) return null

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" className="rounded-full" aria-label="Your account">
          <Avatar className="size-8">
            <AvatarFallback className="text-xs">
              {initials(user.full_name, user.email)}
            </AvatarFallback>
          </Avatar>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-medium">{user.full_name ?? 'Your account'}</p>
          <p className="text-muted-foreground truncate text-xs">{user.email}</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => navigate('/settings/profile')}>
          <UserIcon className="size-4" />
          Your profile
        </DropdownMenuItem>
        <DropdownMenuItem onClick={() => navigate('/settings/household')}>
          <House className="size-4" />
          Household
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={signOut}>
          <LogOut className="size-4" />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
