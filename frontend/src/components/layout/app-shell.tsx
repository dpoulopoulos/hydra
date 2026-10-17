import { Outlet } from 'react-router'

import { AppSidebar } from '@/components/layout/app-sidebar'
import { InviteBanner } from '@/components/layout/invite-banner'
import { PageTrail } from '@/components/layout/page-trail'
import { UserMenu } from '@/components/layout/user-menu'
import { ThemeToggle } from '@/components/theme-toggle'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { useAuth } from '@/hooks/use-auth'
import { LocaleProvider } from '@/lib/locale'
import { VaultProvider } from '@/lib/vault'

export function AppShell() {
  const { user } = useAuth()

  return (
    <LocaleProvider>
      <VaultProvider enabled={Boolean(user?.clients_enabled)}>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            {/* A thin strip: the toggle, where you are, and the two account
                controls. The page below carries its own heading. */}
            <header className="bg-background sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b px-4">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="mr-2 !h-4" />
              <PageTrail />
              <div className="flex-1" />
              <ThemeToggle />
              <UserMenu />
            </header>
            <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
              <InviteBanner />
              <Outlet />
            </div>
          </SidebarInset>
        </SidebarProvider>
      </VaultProvider>
    </LocaleProvider>
  )
}
