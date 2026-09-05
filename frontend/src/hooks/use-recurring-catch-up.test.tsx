import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useRecurringCatchUp } from '@/hooks/use-recurring-catch-up'

// The hook talks to the generated client directly, so the test stands in for
// `POST /recurring-rules/run`: what matters is that it is called once per app
// load, and which caches are dropped when it reports the ledger changed.
vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return { ...actual, recurringRulesRunRecurringRules: vi.fn() }
})

const api = await import('@/api')

/** The result the run endpoint answers with. */
function ran(result: { created_count: number; rules_advanced: number }) {
  vi.mocked(api.recurringRulesRunRecurringRules).mockResolvedValue({
    data: { ...result, skipped_count: 0 },
  } as never)
}

function Harness() {
  useRecurringCatchUp()
  return <p>ready</p>
}

let queryClient: QueryClient
let invalidated: string[]

function renderHarness() {
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  invalidated = []
  vi.spyOn(queryClient, 'invalidateQueries').mockImplementation((filters) => {
    invalidated.push(String((filters?.queryKey ?? [])[0]))
    return Promise.resolve()
  })
})

describe('useRecurringCatchUp', () => {
  it('records what has fallen due once, on mount', async () => {
    ran({ created_count: 0, rules_advanced: 0 })

    const { rerender } = renderHarness()
    rerender(
      <QueryClientProvider client={queryClient}>
        <Harness />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(api.recurringRulesRunRecurringRules).toHaveBeenCalledTimes(1))
  })

  it('drops every cache the new transactions feed', async () => {
    ran({ created_count: 1, rules_advanced: 1 })

    renderHarness()

    await waitFor(() =>
      expect(invalidated.toSorted()).toEqual(['accounts', 'recurring', 'reports', 'transactions']),
    )
  })

  it('drops the caches when a rule moved on without creating anything', async () => {
    ran({ created_count: 0, rules_advanced: 1 })

    renderHarness()

    await waitFor(() => expect(invalidated).toContain('recurring'))
  })

  it('sends a read that was already in flight again', async () => {
    // The dashboard fires its queries as the app loads, so a read can be on
    // the wire while the catch-up is still recording. Left alone it would
    // answer from the ledger as it was, and disagree with the tiles beside it.
    vi.mocked(queryClient.invalidateQueries).mockRestore()
    let releaseRead: () => void = () => {}
    const read = vi.fn(() => new Promise((resolve) => (releaseRead = () => resolve('summary'))))
    ran({ created_count: 1, rules_advanced: 1 })

    function Dashboard() {
      useRecurringCatchUp()
      useQuery({ queryKey: ['reports', 'summary'], queryFn: read })
      return null
    }

    render(
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(read).toHaveBeenCalledTimes(1))
    releaseRead()

    await waitFor(() => expect(read).toHaveBeenCalledTimes(2))
  })

  it('leaves the caches alone when nothing was due', async () => {
    ran({ created_count: 0, rules_advanced: 0 })

    renderHarness()

    await waitFor(() => expect(api.recurringRulesRunRecurringRules).toHaveBeenCalled())
    expect(invalidated).toEqual([])
  })

  it('says nothing when the catch-up fails, leaving the screens as they were', async () => {
    vi.mocked(api.recurringRulesRunRecurringRules).mockResolvedValue({
      error: { detail: 'boom' },
    } as never)

    const { getByText } = renderHarness()

    await waitFor(() => expect(api.recurringRulesRunRecurringRules).toHaveBeenCalled())
    expect(getByText('ready')).toBeInTheDocument()
    expect(invalidated).toEqual([])
  })
})
