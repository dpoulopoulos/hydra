import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ApiTokenPublic } from '@/api'
import { Component as ApiTokensPage } from '@/pages/settings/api-tokens'

// The page talks to the generated client directly, so the tests stand in for
// the endpoints rather than for the component's own hooks.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    apiTokensListApiTokens: vi.fn(),
    apiTokensCreateApiToken: vi.fn(),
    apiTokensRevokeApiToken: vi.fn(),
  }
})

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const { toast } = await import('sonner')

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({ user: { id: 'u1', is_superuser: false }, signOut: vi.fn() }),
}))

const api = await import('@/api')

const token: ApiTokenPublic = {
  id: 't1',
  name: 'Claude',
  token_id: '0123456789abcdef',
  scope: 'read',
  status: 'active',
  expires_at: '2026-12-10T00:00:00',
  last_used_at: null,
  created_at: '2026-09-11T00:00:00',
}

const SECRET = 'hyd_0123456789abcdef_aSecretNobodyElseWillEverSee'

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ApiTokensPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('listing tokens', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('says what each token is for and when it runs out', async () => {
    vi.mocked(api.apiTokensListApiTokens).mockResolvedValue({
      data: { data: [token], count: 1 },
    } as never)

    renderPage()

    expect(await screen.findByText('Claude')).toBeInTheDocument()
    expect(screen.getByText(/Never used/)).toBeInTheDocument()
    expect(screen.getByText(/0123456789abcdef/)).toBeInTheDocument()
  })

  it('invites you to make one when there are none', async () => {
    vi.mocked(api.apiTokensListApiTokens).mockResolvedValue({
      data: { data: [], count: 0 },
    } as never)

    renderPage()

    expect(await screen.findByText('No tokens yet')).toBeInTheDocument()
  })
})

describe('creating a token', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.apiTokensListApiTokens).mockResolvedValue({
      data: { data: [], count: 0 },
    } as never)
    vi.mocked(api.apiTokensCreateApiToken).mockResolvedValue({
      data: { token, secret: SECRET },
    } as never)
  })

  it('shows the secret once, and says it will not be shown again', async () => {
    renderPage()

    await userEvent.type(await screen.findByLabelText('What is it for'), 'Claude')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    expect(await screen.findByText(SECRET)).toBeInTheDocument()
    expect(screen.getByText(/only time it is shown/)).toBeInTheDocument()
  })

  it('the secret goes away when the dialog is dismissed', async () => {
    renderPage()

    await userEvent.type(await screen.findByLabelText('What is it for'), 'Claude')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))
    await screen.findByText(SECRET)

    await userEvent.click(screen.getByRole('button', { name: 'Done' }))

    await waitFor(() => expect(screen.queryByText(SECRET)).not.toBeInTheDocument())
  })

  it('asks for a read token unless told otherwise', async () => {
    renderPage()

    await userEvent.type(await screen.findByLabelText(/What is it for/), 'Claude')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    await waitFor(() =>
      expect(api.apiTokensCreateApiToken).toHaveBeenCalledWith({
        body: { name: 'Claude', scope: 'read', expires_in_days: 90 },
      }),
    )
  })

  it('sends read and write when that is what was picked', async () => {
    // Without this the write tools in the MCP server cannot be reached by a
    // token made the way the app tells you to make one.
    renderPage()

    await userEvent.type(await screen.findByLabelText(/What is it for/), 'Claude')
    await userEvent.click(screen.getByRole('combobox', { name: 'Access' }))
    await userEvent.click(await screen.findByRole('option', { name: 'Read and write' }))
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    await waitFor(() =>
      expect(api.apiTokensCreateApiToken).toHaveBeenCalledWith({
        body: { name: 'Claude', scope: 'read_write', expires_in_days: 90 },
      }),
    )
  })

  it('warns that a write token can change things', async () => {
    vi.mocked(api.apiTokensCreateApiToken).mockResolvedValue({
      data: { token: { ...token, scope: 'read_write' }, secret: SECRET },
    } as never)

    renderPage()

    await userEvent.type(await screen.findByLabelText(/What is it for/), 'Claude')
    await userEvent.click(screen.getByRole('button', { name: 'Create token' }))

    expect(await screen.findByText(/can change your data/)).toBeInTheDocument()
  })

  it('says so when the clipboard refuses, rather than going quiet', async () => {
    // This is the one moment where losing the token costs you the token, so
    // a copy that silently did nothing would be the worst possible failure.
    const user = userEvent.setup()
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('blocked'))

    renderPage()

    await user.type(await screen.findByLabelText(/What is it for/), 'Claude')
    await user.click(screen.getByRole('button', { name: 'Create token' }))
    await screen.findByText(SECRET)

    await user.click(screen.getByRole('button', { name: /Copy token/ }))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/Could not copy/)),
    )
    expect(toast.success).not.toHaveBeenCalledWith('Token copied')
  })

  it('will not send a nameless token', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Create token' }))

    expect(await screen.findByText('Give the token a name.')).toBeInTheDocument()
    expect(api.apiTokensCreateApiToken).not.toHaveBeenCalled()
  })
})

describe('revoking a token', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.apiTokensListApiTokens).mockResolvedValue({
      data: { data: [token], count: 1 },
    } as never)
    vi.mocked(api.apiTokensRevokeApiToken).mockResolvedValue({ data: {} } as never)
  })

  it('asks first, because anything using it stops working', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Revoke Claude' }))

    expect(await screen.findByText('Revoke this token?')).toBeInTheDocument()
    expect(api.apiTokensRevokeApiToken).not.toHaveBeenCalled()
  })

  it('revokes it once confirmed', async () => {
    renderPage()

    await userEvent.click(await screen.findByRole('button', { name: 'Revoke Claude' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke token' }))

    await waitFor(() =>
      expect(api.apiTokensRevokeApiToken).toHaveBeenCalledWith({ path: { token_id: 't1' } }),
    )
  })
})
