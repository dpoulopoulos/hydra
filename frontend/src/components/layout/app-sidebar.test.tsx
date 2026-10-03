import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppSidebar } from '@/components/layout/app-sidebar'
import { SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'

// Mutable, so the same sidebar can be drawn for both kinds of user.
let clientsEnabled = false

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 'u1', clients_enabled: clientsEnabled } }),
}))

// jsdom has no matchMedia, which the sidebar asks to choose its layout.
vi.mock('@/hooks/use-mobile', () => ({ useIsMobile: () => false }))

vi.mock('@/hooks/use-household', () => ({
  useHousehold: () => ({ data: { name: 'Home' } }),
}))

function renderSidebar() {
  render(
    <MemoryRouter>
      <TooltipProvider>
        <SidebarProvider>
          <AppSidebar />
        </SidebarProvider>
      </TooltipProvider>
    </MemoryRouter>,
  )
}

describe('the sidebar', () => {
  beforeEach(() => {
    clientsEnabled = false
  })

  it('leaves Clients out for a user who has not turned it on', () => {
    renderSidebar()

    expect(screen.getByRole('link', { name: /Accounts/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Clients/ })).not.toBeInTheDocument()
  })

  it('lists Goals under planning', () => {
    renderSidebar()

    expect(screen.getByRole('link', { name: /Goals/ })).toHaveAttribute('href', '/goals')
  })

  it('shows Clients to a user who turned it on', () => {
    clientsEnabled = true
    renderSidebar()

    expect(screen.getByRole('link', { name: /Clients/ })).toHaveAttribute('href', '/clients')
  })
})
