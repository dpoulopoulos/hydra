import { describe, expect, it } from 'vitest'

import { compactIban, formatIban, isValidIban } from './iban'

describe('formatIban', () => {
  it('groups an IBAN in fours', () => {
    expect(formatIban('GR1601101250000000012300695')).toBe('GR16 0110 1250 0000 0001 2300 695')
  })
})

describe('compactIban', () => {
  it('strips the spacing and upper cases the letters', () => {
    expect(compactIban('nl29 degi 0123 4567 89')).toBe('NL29DEGI0123456789')
  })
})

describe('isValidIban', () => {
  it('accepts a well formed IBAN', () => {
    expect(isValidIban('DE89370400440532013000')).toBe(true)
    expect(isValidIban('GR1601101250000000012300695')).toBe(true)
    expect(isValidIban('NL29DEGI0123456789')).toBe(true)
  })

  it('rejects one mistyped digit', () => {
    expect(isValidIban('DE89370400440532013001')).toBe(false)
  })

  it('rejects something that is not shaped like an IBAN', () => {
    expect(isValidIban('1234')).toBe(false)
    expect(isValidIban('DE89 3704 0044')).toBe(false)
  })
})
