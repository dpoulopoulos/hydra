import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Component as VerifyEmailPage } from '@/pages/auth/verify-email'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    emailVerificationVerifyEmail: vi.fn(),
    emailVerificationResendVerificationEmail: vi.fn(),
  }
})

const api = await import('@/api')

function renderPage({ token = 'a-token' }: { token?: string } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[token ? `/verify-email?token=${token}` : '/verify-email']}>
        <VerifyEmailPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** Ask for a fresh link from the form the page shows when no token was followed. */
async function askForAnotherLink() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'someone@example.com')
  await user.click(screen.getByRole('button', { name: 'Send a new link' }))
}

describe('verify email', () => {
  beforeEach(() => vi.clearAllMocks())

  it('says what the link actually did', async () => {
    // The same link either activates an account or moves one to a new address,
    // and only the server knows which.
    vi.mocked(api.emailVerificationVerifyEmail).mockResolvedValue({
      data: { message: 'Email address updated successfully.' },
    } as never)

    renderPage()

    expect(await screen.findByText('Email address updated successfully.')).toBeInTheDocument()
  })

  it('says a fresh link is on its way while it is still in the outbox', async () => {
    // The backend answers before the mail necessarily leaves. Saying it is already there sends
    // somebody to an inbox that will stay empty for minutes.
    vi.mocked(api.emailVerificationResendVerificationEmail).mockResolvedValue({
      data: { message: 'ignored', delivery: 'queued' },
    } as never)

    renderPage({ token: '' })
    await askForAnotherLink()

    expect(await screen.findByText('Still sending')).toBeInTheDocument()
    expect(screen.getByText(/should arrive shortly/)).toBeInTheDocument()
  })

  it('says a fresh link has gone out once the provider has taken it', async () => {
    vi.mocked(api.emailVerificationResendVerificationEmail).mockResolvedValue({
      data: { message: 'ignored', delivery: 'sent' },
    } as never)

    renderPage({ token: '' })
    await askForAnotherLink()

    expect(await screen.findByText('Verification sent')).toBeInTheDocument()
  })

  it('says nothing was sent when the server has no mail provider', async () => {
    vi.mocked(api.emailVerificationResendVerificationEmail).mockResolvedValue({
      data: { message: 'ignored', delivery: 'not_configured' },
    } as never)

    renderPage({ token: '' })
    await askForAnotherLink()

    expect(await screen.findByText('No message was sent')).toBeInTheDocument()
    expect(screen.getByText(/not set up on this server/)).toBeInTheDocument()
  })

  it('reports a link that did not work', async () => {
    vi.mocked(api.emailVerificationVerifyEmail).mockResolvedValue({
      error: { detail: 'That token is not valid.' },
    } as never)

    renderPage()

    expect(await screen.findByText('That link will not work')).toBeInTheDocument()
  })
})
