import { describe, expect, it } from 'vitest'

import { MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH, passwordSchema } from '@/lib/password'

/** The message a password is refused with, or null when it is accepted. */
function reject(value: string) {
  const result = passwordSchema.safeParse(value)
  return result.success ? null : result.error.issues[0].message
}

describe('passwordSchema', () => {
  it('takes a password of the minimum length', () => {
    expect(reject('a'.repeat(MIN_PASSWORD_LENGTH))).toBeNull()
  })

  it.each(['', 'short', 'a'.repeat(MIN_PASSWORD_LENGTH - 1)])(
    'refuses %j as too short',
    (value) => {
      expect(reject(value)).toBe('Use at least 8 characters.')
    },
  )

  // The backend hashes with bcrypt, which reads at most 72 bytes and silently
  // ignores the rest, so the limit is bytes and not characters. An emoji is
  // four of them: 18 of these are the whole budget, and 19 are over it.
  it('takes a password of exactly the byte limit', () => {
    expect(reject('a'.repeat(MAX_PASSWORD_BYTES))).toBeNull()
    expect(reject('🔒'.repeat(MAX_PASSWORD_BYTES / 4))).toBeNull()
  })

  it.each(['a'.repeat(MAX_PASSWORD_BYTES + 1), '🔒'.repeat(MAX_PASSWORD_BYTES / 4 + 1)])(
    'refuses a password over the byte limit',
    (value) => {
      expect(reject(value)).toBe('That password is too long. Use at most 72 bytes.')
    },
  )

  it('counts bytes rather than characters, so a short multibyte password fits', () => {
    const password = '🔒'.repeat(MIN_PASSWORD_LENGTH)
    expect(password.length).toBeGreaterThan(MIN_PASSWORD_LENGTH)
    expect(reject(password)).toBeNull()
  })
})
