import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
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

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/verify-email?token=a-token']}>
        <VerifyEmailPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
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

  it('reports a link that did not work', async () => {
    vi.mocked(api.emailVerificationVerifyEmail).mockResolvedValue({
      error: { detail: 'That token is not valid.' },
    } as never)

    renderPage()

    expect(await screen.findByText('That link will not work')).toBeInTheDocument()
  })
})
