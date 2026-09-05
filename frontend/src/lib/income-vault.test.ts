import { describe, expect, it } from 'vitest'

import {
  VaultLockedError,
  createVault,
  decryptText,
  encryptText,
  rewrapVault,
  unlockVault,
} from './income-vault'

// Argon2id is deliberately slow, which is the whole point of it, so these
// tests get a longer budget than the default.
const TIMEOUT = 30_000

describe('the client name vault', () => {
  it(
    'reads back what it encrypted',
    async () => {
      const { dek } = await createVault('123456')

      const ciphertext = await encryptText(dek, 'A. K.')

      expect(await decryptText(dek, ciphertext)).toBe('A. K.')
    },
    TIMEOUT,
  )

  it(
    'never stores the name in the clear',
    async () => {
      const { dek } = await createVault('123456')

      const ciphertext = await encryptText(dek, 'A. K.')

      expect(ciphertext).not.toContain('A. K.')
    },
    TIMEOUT,
  )

  it(
    'gives the same name different ciphertext every time',
    async () => {
      // A fresh nonce each time, so the database cannot be read for which two
      // clients share a name.
      const { dek } = await createVault('123456')

      expect(await encryptText(dek, 'A. K.')).not.toBe(await encryptText(dek, 'A. K.'))
    },
    TIMEOUT,
  )

  it(
    'opens with the right PIN',
    async () => {
      const { params, wrappedDek, dek } = await createVault('123456')
      const ciphertext = await encryptText(dek, 'A. K.')

      const reopened = await unlockVault('123456', params, wrappedDek)

      expect(await decryptText(reopened, ciphertext)).toBe('A. K.')
    },
    TIMEOUT,
  )

  it(
    'refuses the wrong PIN',
    async () => {
      const { params, wrappedDek } = await createVault('123456')

      await expect(unlockVault('654321', params, wrappedDek)).rejects.toBeInstanceOf(
        VaultLockedError,
      )
    },
    TIMEOUT,
  )

  it(
    'keeps every name readable after a PIN change',
    async () => {
      // The names are encrypted with the data key, not the PIN, so changing the
      // PIN re-wraps one key and rewrites no client row.
      const { params, wrappedDek, dek } = await createVault('123456')
      const ciphertext = await encryptText(dek, 'A. K.')

      const changed = await rewrapVault(dek, 'newpin789')
      const reopened = await unlockVault('newpin789', changed.params, changed.wrappedDek)

      expect(await decryptText(reopened, ciphertext)).toBe('A. K.')
      expect(changed.wrappedDek).not.toBe(wrappedDek)
      expect(changed.params.kdf_salt).not.toBe(params.kdf_salt)
    },
    TIMEOUT,
  )

  it(
    'stops the old PIN working after a change',
    async () => {
      const { dek } = await createVault('123456')

      const changed = await rewrapVault(dek, 'newpin789')

      await expect(
        unlockVault('123456', changed.params, changed.wrappedDek),
      ).rejects.toBeInstanceOf(VaultLockedError)
    },
    TIMEOUT,
  )

  it(
    'refuses a name belonging to a different key',
    async () => {
      const mine = await createVault('123456')
      const theirs = await createVault('123456')
      const ciphertext = await encryptText(theirs.dek, 'A. K.')

      await expect(decryptText(mine.dek, ciphertext)).rejects.toBeInstanceOf(VaultLockedError)
    },
    TIMEOUT,
  )
})
