import { useLocation } from 'react-router'

import { NAV_GROUPS, SETTINGS_PAGES } from '@/components/layout/nav'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'

/** The group and screen a path belongs to, or nothing for one the nav does not list. */
function trailFor(pathname: string): { group: string; page: string } | null {
  if (pathname.startsWith('/settings')) {
    const page = SETTINGS_PAGES.find((item) => pathname.startsWith(item.to))
    // The bare /settings address shows the household screen.
    return { group: 'Settings', page: page?.label ?? SETTINGS_PAGES[0].label }
  }

  for (const group of NAV_GROUPS) {
    const item = group.items.find((candidate) =>
      candidate.to === '/' ? pathname === '/' : pathname.startsWith(candidate.to),
    )
    if (item) return { group: group.label, page: item.label }
  }

  return null
}

/**
 * Where you are, as "Group / Screen", in the top bar.
 *
 * The sidebar already shows this when it is open. On a phone it is closed,
 * and this is then the only sign of which part of the app is on screen.
 */
export function PageTrail() {
  const { pathname } = useLocation()
  const trail = trailFor(pathname)

  if (!trail) return null

  return (
    <Breadcrumb>
      <BreadcrumbList className="text-xs sm:text-sm">
        <BreadcrumbItem>{trail.group}</BreadcrumbItem>
        <BreadcrumbSeparator />
        <BreadcrumbItem>
          <BreadcrumbPage>{trail.page}</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
  )
}
