import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { incomeGetVault, incomeUpsertVault } from '@/api'
import { createVault, decryptText, encryptText, rewrapVault, unlockVault } from '@/lib/income-vault'
import { VaultContext, type VaultValue } from '@/lib/vault-context'

/**
 * How long the names stay readable without any activity on the page.
 *
 * A practice room is not a private office. Fifteen minutes is long enough to
 * write up a session and short enough that a screen left open in a waiting area
 * is not a list of who you see.
 */
const AUTO_LOCK_MS = 15 * 60_000

/**
 * What counts as somebody still being at the screen.
 *
 * Deliberately coarse. Anything finer would reset the countdown on a cursor
 * drifting across the page, which is not the same as a person being there.
 *
 * `focusin` rather than `focus`, because focus does not bubble: on `window` it
 * would only ever fire when the whole tab came back, never when somebody moved
 * between fields on the page.
 */
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'focusin'] as const

export function VaultProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  // The unwrapped key lives here and only here: never localStorage, never
  // sessionStorage, never a cookie. Closing the tab is what locks it, and there
  // is nothing left behind on the disk to find afterwards.
  const [dek, setDek] = useState<CryptoKey | null>(null)
  const lockTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const vault = useQuery({
    queryKey: ['income-vault'],
    queryFn: async () => {
      const { data, error } = await incomeGetVault()
      // A 404 is the ordinary answer for somebody who has not set a PIN yet,
      // so it is a state rather than a failure.
      if (error) return null
      return data ?? null
    },
    retry: false,
    staleTime: 5 * 60_000,
  })

  // Locking has to take the decrypted names with it. They are cached by
  // ciphertext so a name shown in three rows is only decrypted once, and
  // leaving that cache behind would leave a locked page full of plaintext.
  const forget = useCallback(() => {
    setDek(null)
    queryClient.removeQueries({ queryKey: ['decrypted'] })
  }, [queryClient])

  const lock = useCallback(() => {
    if (lockTimer.current) clearTimeout(lockTimer.current)
    lockTimer.current = null
    forget()
  }, [forget])

  const hold = useCallback(
    (key: CryptoKey) => {
      if (lockTimer.current) clearTimeout(lockTimer.current)
      lockTimer.current = setTimeout(forget, AUTO_LOCK_MS)
      setDek(key)
    },
    [forget],
  )

  // Idle, not elapsed. Counting from the moment of unlocking would lock the
  // names while somebody was still typing into them, which is a worse answer
  // than leaving them open: they would simply stop using the PIN.
  useEffect(() => {
    if (!dek) return

    const postpone = () => {
      if (lockTimer.current) clearTimeout(lockTimer.current)
      lockTimer.current = setTimeout(forget, AUTO_LOCK_MS)
    }

    for (const event of ACTIVITY_EVENTS) {
      window.addEventListener(event, postpone, { passive: true })
    }

    return () => {
      for (const event of ACTIVITY_EVENTS) window.removeEventListener(event, postpone)
    }
  }, [dek, forget])

  const setUp = useCallback(
    async (pin: string) => {
      const { params, wrappedDek, dek: key } = await createVault(pin)
      const { error } = await incomeUpsertVault({
        body: { ...params, kdf: 'argon2id', wrapped_dek: wrappedDek },
      })
      if (error) throw error

      hold(key)
      await queryClient.invalidateQueries({ queryKey: ['income-vault'] })
    },
    [hold, queryClient],
  )

  const unlock = useCallback(
    async (pin: string) => {
      if (!vault.data) throw new Error('There is no PIN to unlock yet.')
      hold(await unlockVault(pin, vault.data, vault.data.wrapped_dek))
    },
    [vault.data, hold],
  )

  const changePin = useCallback(
    async (pin: string) => {
      if (!dek) throw new Error('Unlock the names before changing the PIN.')

      // Only the wrapper changes. Every client row is left exactly as it is,
      // which is why this cannot half fail and leave some names unreadable.
      const { params, wrappedDek } = await rewrapVault(dek, pin)
      const { error } = await incomeUpsertVault({
        body: { ...params, kdf: 'argon2id', wrapped_dek: wrappedDek },
      })
      if (error) throw error

      await queryClient.invalidateQueries({ queryKey: ['income-vault'] })
    },
    [dek, queryClient],
  )

  const encrypt = useCallback(
    async (text: string) => {
      if (!dek) throw new Error('Unlock the names first.')
      return encryptText(dek, text)
    },
    [dek],
  )

  const decrypt = useCallback(
    async (ciphertext: string) => {
      if (!dek || !ciphertext) return null
      try {
        return await decryptText(dek, ciphertext)
      } catch {
        // A name written under a key that has since been reset. Showing the
        // row without a name is better than failing the whole page.
        return null
      }
    },
    [dek],
  )

  const value = useMemo<VaultValue>(() => {
    const status = vault.isPending
      ? 'loading'
      : !vault.data
        ? 'absent'
        : dek
          ? 'unlocked'
          : 'locked'
    return { status, unlock, setUp, changePin, lock, encrypt, decrypt }
  }, [vault.isPending, vault.data, dek, unlock, setUp, changePin, lock, encrypt, decrypt])

  return <VaultContext value={value}>{children}</VaultContext>
}
