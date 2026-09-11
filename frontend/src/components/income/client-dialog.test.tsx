import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { IncomeClientPublic } from '@/api'
import { ClientDialog } from '@/components/income/client-dialog'
import { VaultContext, type VaultValue } from '@/lib/vault-context'

// The dialog talks to the generated client directly for its accounts, its
// categories and the household currency, so the tests stand in for those
// endpoints and read back the body it sent.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    incomeCreateClient: vi.fn(),
    incomeUpdateClient: vi.fn(),
    accountsListAccounts: vi.fn(),
    categoriesGetCategoryTree: vi.fn(),
    householdsGetHouseholdMe: vi.fn(),
  }
})

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}))

const api = await import('@/api')

const ACCOUNT = '11111111-1111-1111-1111-111111111111'

/** A vault that is open, and whose ciphertext is the name in brackets. */
function vault(): VaultValue {
  return {
    status: 'unlocked',
    unlock: vi.fn(),
    setUp: vi.fn(),
    changePin: vi.fn(),
    lock: vi.fn(),
    encrypt: (text: string) => Promise.resolve(`cipher(${text})`),
    // What `encrypt` wrote, read back the same way the vault reads it: a
    // promise, so the plaintext lands a render or two after the dialog opens.
    decrypt: (text: string) => Promise.resolve(/^cipher\((.*)\)$/.exec(text)?.[1] ?? null),
  }
}

/** A stored client, whose name and note only this device can read. */
function storedClient(): IncomeClientPublic {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    household_id: 'h',
    owner_user_id: 'u',
    name_ct: 'cipher(Anna)',
    note_ct: 'cipher(Fridays, upstairs room)',
    default_rate_minor: 5000,
    default_account_id: ACCOUNT,
    default_category_id: null,
    cadence_frequency: null,
    cadence_interval: 1,
    cadence_anchor_on: null,
    cadence_weekdays: [],
    archived_at: null,
    created_at: '2026-01-01T00:00:00Z',
  }
}

function renderDialog(editing: IncomeClientPublic | null = null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <VaultContext value={vault()}>
        <ClientDialog open client={editing} onOpenChange={() => {}} />
      </VaultContext>
    </QueryClientProvider>,
  )
}

/** The body the last create call sent. */
function createdBody() {
  const call = vi.mocked(api.incomeCreateClient).mock.calls.at(-1)
  return (call?.[0] as { body: Record<string, unknown> }).body
}

beforeEach(() => {
  vi.mocked(api.accountsListAccounts).mockResolvedValue({
    data: {
      data: [
        {
          id: ACCOUNT,
          household_id: 'h',
          name: 'Current',
          type: 'current',
          currency_code: 'EUR',
          opening_balance_minor: 0,
          opening_balance_date: '2026-01-01',
          current_balance_minor: 0,
          archived_at: null,
          created_at: '2026-01-01T00:00:00Z',
        },
      ],
      count: 1,
    },
  } as never)
  vi.mocked(api.categoriesGetCategoryTree).mockResolvedValue({
    data: { data: [], count: 0 },
  } as never)
  vi.mocked(api.householdsGetHouseholdMe).mockResolvedValue({
    data: { id: 'h', name: 'Home', currency_code: 'EUR' },
  } as never)
  vi.mocked(api.incomeCreateClient).mockResolvedValue({ data: {} } as never)
})

describe('the fee the dialog echoes back', () => {
  it('reads a fee typed with a thousands separator as thousands', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '1,200')

    expect(await screen.findByText(/€1,200\.00 a session/)).toBeInTheDocument()
  })

  it('reads a fee typed plainly', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '42.50')

    expect(await screen.findByText(/€42\.50 a session/)).toBeInTheDocument()
  })

  it('reads a fee typed with a comma for the decimals', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '42,50')

    expect(await screen.findByText(/€42\.50 a session/)).toBeInTheDocument()
  })

  // The read-back used to run the field through a plain `Number()`, which a
  // thousands space makes NaN, so this fee vanished from the sentence while
  // the form was quite happily about to save it.
  it('reads a fee typed with a thousands space', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '1 000')

    expect(await screen.findByText(/€1,000\.00 a session/)).toBeInTheDocument()
  })

  it('says nothing about the fee while the field is empty', async () => {
    renderDialog()

    await screen.findByLabelText('Usual fee')

    expect(screen.queryByText(/a session/)).not.toBeInTheDocument()
  })

  it('says nothing about a fee it cannot read', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '1,2,3')

    expect(screen.queryByText(/a session/)).not.toBeInTheDocument()
  })

  it('stays quiet about a fee the form will refuse to save', async () => {
    const user = userEvent.setup()
    renderDialog()

    // Read as 12000 by a bare `Number()`, rejected by the form's schema. The
    // sentence must not promise money the save will not send.
    await user.type(await screen.findByLabelText('Usual fee'), '12e3')

    expect(screen.queryByText(/a session/)).not.toBeInTheDocument()
  })

  it('stays quiet while the fee is still half typed', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), 'ab')

    expect(screen.queryByText(/a session/)).not.toBeInTheDocument()
  })
})

describe('adding a client', () => {
  it('sends the name encrypted, with the fee and the account picked', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Anna')
    await user.type(screen.getByLabelText('Usual fee'), '50')
    await user.click(screen.getByRole('combobox', { name: 'Lands in' }))
    await user.click(await screen.findByRole('option', { name: 'Current' }))
    await user.click(screen.getByRole('button', { name: 'Add client' }))

    await waitFor(() => expect(api.incomeCreateClient).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({
      name_ct: 'cipher(Anna)',
      default_rate_minor: 5000,
      default_account_id: ACCOUNT,
      cadence_frequency: null,
    })
  })

  it('carries the cadence that was picked, with the days it repeats on', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Name'), 'Anna')
    await user.type(screen.getByLabelText('Usual fee'), '50')
    await user.click(screen.getByRole('combobox', { name: 'Lands in' }))
    await user.click(await screen.findByRole('option', { name: 'Current' }))

    await user.click(screen.getByRole('combobox', { name: 'How often' }))
    await user.click(await screen.findByRole('option', { name: 'Every week' }))
    await user.click(await screen.findByRole('button', { name: 'Tuesday' }))
    await user.click(screen.getByRole('button', { name: 'Add client' }))

    await waitFor(() => expect(api.incomeCreateClient).toHaveBeenCalled())
    expect(createdBody()).toMatchObject({
      cadence_frequency: 'weekly',
      cadence_interval: 1,
      cadence_weekdays: [1],
    })
  })

  it('says back the schedule the form currently describes', async () => {
    const user = userEvent.setup()
    renderDialog()

    await user.type(await screen.findByLabelText('Usual fee'), '50')
    expect(await screen.findByText(/€50.00 a session/)).toBeInTheDocument()

    await user.click(screen.getByRole('combobox', { name: 'How often' }))
    await user.click(await screen.findByRole('option', { name: 'Every 2 weeks' }))

    // The sentence, not the option of the same name in the picker above it.
    expect(await screen.findByText(/Every 2 weeks.*€50.00 a session\./)).toBeInTheDocument()
  })
})

describe('editing a client', () => {
  beforeEach(() => {
    vi.mocked(api.incomeUpdateClient).mockResolvedValue({ data: {} } as never)
  })

  // The dialog is already open when the decrypt lands, so this is the second
  // time the form is filled: the one a memoized render will not repeat any
  // `register()` call for.
  it('shows the name and the note once they come back decrypted', async () => {
    renderDialog(storedClient())

    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('Anna'))
    expect(screen.getByLabelText('Note')).toHaveValue('Fridays, upstairs room')
  })

  it('saves what the decrypted fields show, edited', async () => {
    const user = userEvent.setup()
    renderDialog(storedClient())

    const name = await screen.findByLabelText('Name')
    await waitFor(() => expect(name).toHaveValue('Anna'))
    await user.clear(name)
    await user.type(name, 'Anna B')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(api.incomeUpdateClient).toHaveBeenCalled())
    const call = vi.mocked(api.incomeUpdateClient).mock.calls.at(-1)
    expect((call?.[0] as { body: Record<string, unknown> }).body).toMatchObject({
      name_ct: 'cipher(Anna B)',
      note_ct: 'cipher(Fridays, upstairs room)',
      default_rate_minor: 5000,
    })
  })
})
