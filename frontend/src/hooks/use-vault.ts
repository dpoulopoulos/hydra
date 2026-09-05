import { useQuery } from '@tanstack/react-query'
import { useContext } from 'react'

import { VaultContext, type VaultValue } from '@/lib/vault-context'

/** The client-name vault for the current household. */
export function useVault(): VaultValue {
  const value = useContext(VaultContext)
  if (!value) throw new Error('useVault must be used inside a VaultProvider.')
  return value
}

/**
 * Decrypt one stored name for display.
 *
 * Returns null while the vault is locked, which is what the page renders as
 * dots. Decryption is asynchronous, so it cannot be a plain call in the middle
 * of a table row; a query rather than an effect, so the same name appearing in
 * three rows is decrypted once and read three times.
 *
 * Locking drops every one of these from the cache, so no plaintext is left
 * sitting behind a locked page.
 */
export function useDecrypted(ciphertext: string | null | undefined): string | null {
  const { decrypt, status } = useVault()

  const { data } = useQuery({
    queryKey: ['decrypted', ciphertext],
    queryFn: () => decrypt(ciphertext ?? ''),
    enabled: status === 'unlocked' && Boolean(ciphertext),
    // The key never changes meaning: this ciphertext always decrypts to this
    // name, so there is nothing to go stale.
    staleTime: Infinity,
    gcTime: Infinity,
  })

  return status === 'unlocked' ? (data ?? null) : null
}
