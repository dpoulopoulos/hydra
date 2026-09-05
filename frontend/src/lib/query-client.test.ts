import { describe, expect, it } from 'vitest'

import { retryUnlessRejected } from '@/lib/query-client'

describe('retryUnlessRejected', () => {
  it('does not repeat a request the server rejected', () => {
    expect(retryUnlessRejected(0, { status: 401 })).toBe(false)
  })

  it('tries a failure the server did not choose twice more', () => {
    expect(retryUnlessRejected(0, { status: 502 })).toBe(true)
    expect(retryUnlessRejected(1, { status: 502 })).toBe(true)
    expect(retryUnlessRejected(2, { status: 502 })).toBe(false)
  })

  it('tries again when the request never reached the server', () => {
    expect(retryUnlessRejected(0, new TypeError('Failed to fetch'))).toBe(true)
  })
})
