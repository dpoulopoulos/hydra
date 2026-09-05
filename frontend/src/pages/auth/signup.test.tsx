import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Component as SignUp } from '@/pages/auth/signup'

// The page talks to the generated client directly, so the endpoints are stood
// in for here: what matters is what the form holds while the invite preview is
// still in flight, what it still holds once the answer arrives, and that the
// screen the page paints does not depend on what the registration reply says.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    householdsPreviewHouseholdInvite: vi.fn(),
    usersRegisterUser: vi.fn(),
  }
})

const api = await import('@/api')

const TOKEN = 'invite-token'
const INVITED_EMAIL = 'alex@example.com'
// The preview only ever names the invited address masked, so the form asks for
// it rather than filling it in.
const MASKED_EMAIL = 'a***@example.com'
const EMAIL = 'someone@example.com'

/** A preview that only answers once the returned callback is called. */
function previewPending() {
  let resolve!: () => void
  const answered = new Promise<void>((r) => (resolve = r))
  vi.mocked(api.householdsPreviewHouseholdInvite).mockImplementation((async () => {
    await answered
    return {
      data: { masked_email: MASKED_EMAIL, household_name: 'Rivera', invited_by: 'Sam Rivera' },
    }
  }) as never)
  return resolve
}

function renderSignUp({ token }: { token?: string } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[token ? `/signup?token=${token}` : '/signup']}>
        <SignUp />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const nameField = () => screen.getByLabelText('Name')
const emailField = () => screen.getByLabelText('Email')
const passwordField = () => screen.getByLabelText('Password')

describe('sign-up page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('names the invited address once the preview arrives', async () => {
    const answer = previewPending()
    renderSignUp({ token: TOKEN })

    expect(emailField()).toHaveValue('')

    answer()
    await waitFor(() => expect(screen.getByText(/Use the invited address/)).toBeInTheDocument())
    expect(screen.getByText(new RegExp(MASKED_EMAIL.replace(/\*/g, '\\*')))).toBeInTheDocument()
  })

  it('keeps what was typed while the invite preview was still in flight', async () => {
    const user = userEvent.setup()
    const answer = previewPending()
    renderSignUp({ token: TOKEN })

    await user.type(nameField(), 'Alex Rivera')
    await user.type(emailField(), INVITED_EMAIL)
    await user.type(passwordField(), 'correct horse')

    answer()
    await waitFor(() => expect(screen.getByText(/Use the invited address/)).toBeInTheDocument())

    expect(nameField()).toHaveValue('Alex Rivera')
    expect(emailField()).toHaveValue(INVITED_EMAIL)
    expect(passwordField()).toHaveValue('correct horse')
  })

  it('submits what was typed together with the invitation', async () => {
    const user = userEvent.setup()
    const answer = previewPending()
    vi.mocked(api.usersRegisterUser).mockResolvedValue({
      data: { email: INVITED_EMAIL },
    } as never)
    renderSignUp({ token: TOKEN })

    await user.type(nameField(), 'Alex Rivera')
    await user.type(emailField(), INVITED_EMAIL)
    await user.type(passwordField(), 'correct horse')
    answer()
    await waitFor(() => expect(screen.getByText(/Use the invited address/)).toBeInTheDocument())

    await user.click(screen.getByRole('button', { name: 'Create account' }))

    await waitFor(() => expect(api.usersRegisterUser).toHaveBeenCalled())
    expect(vi.mocked(api.usersRegisterUser).mock.calls[0][0]).toMatchObject({
      body: {
        email: INVITED_EMAIL,
        full_name: 'Alex Rivera',
        password: 'correct horse',
        invite_token: TOKEN,
      },
    })
  })
})

/** Fill the form with an address and send it. */
async function signUpWith(email: string) {
  const user = userEvent.setup()
  await user.type(emailField(), email)
  await user.type(passwordField(), 'password123')
  await user.click(screen.getByRole('button', { name: 'Create account' }))
}

describe('signing up', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // The one reply signup has, for an address that is free and for one that
    // is taken alike.
    vi.mocked(api.usersRegisterUser).mockResolvedValue({
      data: {
        message: 'Check your email. We sent a message to that address with what to do next.',
      },
    } as never)
  })

  it('confirms the address that was typed, which the reply no longer carries', async () => {
    renderSignUp()

    await signUpWith(EMAIL)

    expect(await screen.findByText(`Message sent to ${EMAIL}`)).toBeInTheDocument()
  })

  it('says nothing about whether the address already has an account', async () => {
    renderSignUp()

    await signUpWith(EMAIL)

    expect(await screen.findByText('Check your email')).toBeInTheDocument()
    expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Conflict/i)).not.toBeInTheDocument()
  })
})
