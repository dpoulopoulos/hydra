import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { UserPublic } from '@/api'
import { useAuth } from '@/hooks/use-auth'
import { AuthProvider } from '@/lib/auth'
import { retryUnlessRejected } from '@/lib/query-client'

// The provider asks the API who the stored token belongs to, and the answer to
// that one call decides whether the app shows the dashboard or the sign-in
// screen. The tests stand in for the call and read the decision.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, usersGetUserMe: vi.fn() }
})

const api = await import('@/api')

const USER: UserPublic = {
  id: '11111111-1111-1111-1111-111111111111',
  email: 'sam@example.com',
  is_active: true,
  is_superuser: false,
  full_name: 'Sam',
  created_at: '2026-01-01T00:00:00Z',
}

/** Reads the decision the provider reached, so a test can assert on it. */
function Probe() {
  const { isLoading, isAuthenticated, isUnauthenticated, error, isRetrying, retry } = useAuth()
  return (
    <>
      <button onClick={retry}>Try again</button>
      <dl>
        <dd data-testid="loading">{String(isLoading)}</dd>
        <dd data-testid="authenticated">{String(isAuthenticated)}</dd>
        <dd data-testid="unauthenticated">{String(isUnauthenticated)}</dd>
        <dd data-testid="error">{String(Boolean(error))}</dd>
        <dd data-testid="retrying">{String(isRetrying)}</dd>
      </dl>
    </>
  )
}

function renderAuth() {
  // The real retry policy, with the waiting taken out.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: retryUnlessRejected, retryDelay: 0 } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

function state(name: string) {
  return screen.getByTestId(name).textContent
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.setItem('hydra.token', 'a-valid-token')
})

afterEach(() => {
  localStorage.clear()
})

describe('the session behind a stored token', () => {
  it('is over when there is no token at all', () => {
    localStorage.clear()

    renderAuth()

    expect(state('unauthenticated')).toBe('true')
    expect(state('loading')).toBe('false')
    expect(api.usersGetUserMe).not.toHaveBeenCalled()
  })

  it('holds when the token is good', async () => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({ data: USER } as never)

    renderAuth()

    await waitFor(() => expect(state('authenticated')).toBe('true'))
    expect(state('unauthenticated')).toBe('false')
    expect(state('error')).toBe('false')
  })

  it('is over when the API rejects the token', async () => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({
      error: { detail: 'Not authenticated', status: 401 },
    } as never)

    renderAuth()

    await waitFor(() => expect(state('unauthenticated')).toBe('true'))
    expect(state('error')).toBe('false')
    // A rejection is the server's considered answer: asking again only repeats it.
    expect(api.usersGetUserMe).toHaveBeenCalledTimes(1)
  })

  // /users/me answers 403 when the account is no longer active and 404 when
  // the record is gone. Neither clears by being asked again, so both are the
  // end of the session and not a check that could not be made.
  it.each([403, 404])('is over when the API answers %i', async (status) => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({ error: { status } } as never)

    renderAuth()

    await waitFor(() => expect(state('unauthenticated')).toBe('true'))
    expect(state('error')).toBe('false')
    expect(api.usersGetUserMe).toHaveBeenCalledTimes(1)
  })

  it('survives a backend that is restarting', async () => {
    vi.mocked(api.usersGetUserMe)
      .mockResolvedValueOnce({ error: { status: 502 } } as never)
      .mockResolvedValue({ data: USER } as never)

    renderAuth()

    await waitFor(() => expect(state('authenticated')).toBe('true'))
    expect(state('unauthenticated')).toBe('false')
  })

  it('is not called over when the request never got an answer', async () => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({ error: { status: 502 } } as never)

    renderAuth()

    await waitFor(() => expect(state('error')).toBe('true'))
    expect(state('unauthenticated')).toBe('false')
    expect(state('loading')).toBe('false')
    expect(state('retrying')).toBe('false')
    expect(api.usersGetUserMe).toHaveBeenCalledTimes(3)
  })

  it('keeps the failure on screen while it is being asked again', async () => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({ error: { status: 502 } } as never)

    renderAuth()
    await waitFor(() => expect(state('error')).toBe('true'))

    // A check that never succeeded starts over when asked again, error and
    // all, so the failure has to outlive the query for the screen reporting
    // it to stay put — with the wait shown there rather than as a full page
    // spinner over the top of it.
    let answer: (value: unknown) => void = () => {}
    vi.mocked(api.usersGetUserMe).mockReturnValue(
      new Promise((resolve) => {
        answer = resolve
      }) as never,
    )

    await userEvent.click(screen.getByRole('button', { name: /try again/i }))

    await waitFor(() => expect(state('retrying')).toBe('true'))
    expect(state('error')).toBe('true')
    expect(state('loading')).toBe('false')

    answer({ data: USER })

    await waitFor(() => expect(state('authenticated')).toBe('true'))
    expect(state('error')).toBe('false')
    expect(state('retrying')).toBe('false')
  })

  it('keeps the failure on screen when the tab regains focus', async () => {
    vi.mocked(api.usersGetUserMe).mockResolvedValue({ error: { status: 502 } } as never)

    renderAuth()
    await waitFor(() => expect(state('error')).toBe('true'))

    // The check refetches on focus, and a returning tab is the likeliest way
    // to hit it during a backend restart. That repeat starts the query over
    // like any other, so the failure has to outlive it here too.
    let answer: (value: unknown) => void = () => {}
    vi.mocked(api.usersGetUserMe).mockReturnValue(
      new Promise((resolve) => {
        answer = resolve
      }) as never,
    )

    window.dispatchEvent(new Event('visibilitychange'))
    document.dispatchEvent(new Event('visibilitychange'))

    await waitFor(() => expect(state('retrying')).toBe('true'))
    expect(state('error')).toBe('true')
    expect(state('loading')).toBe('false')

    answer({ data: USER })
    await waitFor(() => expect(state('authenticated')).toBe('true'))
    expect(state('error')).toBe('false')
  })
})
