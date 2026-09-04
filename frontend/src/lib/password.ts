import { z } from 'zod'

// The backend hashes with bcrypt, which takes at most 72 bytes, and asks for
// at least 8 characters. Kept in one place so every password field on the
// front end explains the same rule before the request rather than after it.
export const MIN_PASSWORD_LENGTH = 8
export const MAX_PASSWORD_BYTES = 72

export const passwordSchema = z
  .string()
  .min(MIN_PASSWORD_LENGTH, `Use at least ${MIN_PASSWORD_LENGTH} characters.`)
  .refine((value) => new TextEncoder().encode(value).length <= MAX_PASSWORD_BYTES, {
    message: `That password is too long. Use at most ${MAX_PASSWORD_BYTES} bytes.`,
  })

export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LENGTH} characters.`
