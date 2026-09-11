import { Outlet } from 'react-router'

import { AppSidebar } from '@/components/layout/app-sidebar'
import { UserMenu } from '@/components/layout/user-menu'
import { ThemeToggle } from '@/components/theme-toggle'
import { Separator } from '@/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { LocaleProvider } from '@/lib/locale'
import { VaultProvider } from '@/lib/vault'

export function AppShell() {
  return (
    <LocaleProvider>
      <VaultProvider>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            <header className="bg-background/80 sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b px-4 backdrop-blur">
              <SidebarTrigger className="-ml-1" />
              <Separator orientation="vertical" className="mr-2 !h-4" />
              <div className="flex-1" />
              <ThemeToggle />
              <UserMenu />
            </header>
            <div className="flex flex-1 flex-col gap-6 p-4 md:p-6">
              <Outlet />
            </div>
          </SidebarInset>
        </SidebarProvider>
      </VaultProvider>
    </LocaleProvider>
  )
}
