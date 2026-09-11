import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Money } from '@/components/money'
import { LocaleContext } from '@/lib/locale-context'

function renderIn(locale: string | undefined, ui: React.ReactNode) {
  return render(<LocaleContext value={locale}>{ui}</LocaleContext>)
}

describe('Money', () => {
  // The suite reads as en-US, so this is the household overruling the browser
  // rather than the two happening to agree.
  it('writes the figure the way the household writes numbers', () => {
    renderIn('de-DE', <Money minor={120050} currency="EUR" />)

    expect(screen.getByText('1.200,50 €')).toBeInTheDocument()
  })

  it('signs the figure in the household locale too', () => {
    renderIn('de-DE', <Money minor={120050} currency="EUR" signed />)

    expect(screen.getByText('+1.200,50 €')).toBeInTheDocument()
  })

  it("falls back to the reader's own browser when the household named none", () => {
    renderIn(undefined, <Money minor={120050} currency="EUR" />)

    expect(screen.getByText('€1,200.50')).toBeInTheDocument()
  })
})
