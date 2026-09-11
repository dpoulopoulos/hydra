import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { LocaleProvider } from '@/lib/locale'
import { useLocale } from '@/lib/locale-context'

const household = vi.hoisted(() => ({ data: undefined as { locale?: string | null } | undefined }))

vi.mock('@/hooks/use-household', () => ({ useHousehold: () => household }))

function Reader() {
  return <p>{useLocale() ?? 'the browser'}</p>
}

describe('LocaleProvider', () => {
  it('hands down the locale the household writes its numbers in', () => {
    household.data = { locale: 'de-DE' }

    render(
      <LocaleProvider>
        <Reader />
      </LocaleProvider>,
    )

    expect(screen.getByText('de-DE')).toBeInTheDocument()
  })

  // A household that has named none leaves every reader with their own
  // browser, which is what an unnamed locale means everywhere below.
  it('names no locale for a household that has not chosen one', () => {
    household.data = { locale: null }

    render(
      <LocaleProvider>
        <Reader />
      </LocaleProvider>,
    )

    expect(screen.getByText('the browser')).toBeInTheDocument()
  })

  it('names no locale while the household is still loading', () => {
    household.data = undefined

    render(
      <LocaleProvider>
        <Reader />
      </LocaleProvider>,
    )

    expect(screen.getByText('the browser')).toBeInTheDocument()
  })
})

describe('useLocale', () => {
  // Outside the provider there is no household to ask, which is the honest
  // answer on a screen that has none: the reader's own browser.
  it('names no locale outside the provider', () => {
    render(<Reader />)

    expect(screen.getByText('the browser')).toBeInTheDocument()
  })
})
