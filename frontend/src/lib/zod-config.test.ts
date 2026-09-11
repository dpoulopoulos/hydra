import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { configureZod } from '@/lib/zod-config'

describe('configureZod', () => {
  it('keeps zod off the path that needs new Function', () => {
    configureZod()

    expect(z.config().jitless).toBe(true)
  })

  it('leaves a schema validating exactly as before', () => {
    configureZod()
    const schema = z.object({ email: z.email(), amount: z.number().min(0) })

    expect(schema.safeParse({ email: 'a@example.com', amount: 1 }).success).toBe(true)
    expect(schema.safeParse({ email: 'not an email', amount: 1 }).success).toBe(false)
    expect(schema.safeParse({ email: 'a@example.com', amount: -1 }).success).toBe(false)
  })
})
