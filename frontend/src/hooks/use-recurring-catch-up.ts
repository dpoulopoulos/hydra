import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { recurringRulesRunRecurringRules } from '@/api'

/** Every cache a newly recorded transaction can change. */
const AFFECTED_KEYS = [['recurring'], ['reports'], ['transactions'], ['accounts']]

/**
 * Records the recurring transactions that have fallen due, once per app load.
 *
 * Materialising is a write, so it happens here rather than inside whichever
 * read the screen fires first: every read endpoint then answers from the same
 * ledger, instead of the first one to arrive deciding what the others see.
 *
 * The reads on screen are not held back for it, so a catch-up that does record
 * something drops the caches it invalidated behind it and they refetch
 * together. A failure is left alone: nothing is recorded, every screen still
 * shows the ledger as it stands, and the Recurring page can run it explicitly.
 */
export function useRecurringCatchUp() {
  const queryClient = useQueryClient()
  const started = useRef(false)

  useEffect(() => {
    // Guarded rather than keyed off the effect, so a remount in development's
    // double-invoked Strict Mode does not fire a second write.
    if (started.current) return
    started.current = true

    void (async () => {
      const { data, error } = await recurringRulesRunRecurringRules({})
      if (error || !data) return

      // Nothing moved, so every cache still matches the ledger.
      if (data.created_count === 0 && data.rules_advanced === 0) return

      for (const queryKey of AFFECTED_KEYS) {
        // A read that is still in flight was sent before the transactions
        // existed, and invalidating alone would keep whatever it answers.
        // Cancelling it first means every figure on the screen comes from a
        // request that left after the write.
        await queryClient.cancelQueries({ queryKey })
        void queryClient.invalidateQueries({ queryKey })
      }
    })()
  }, [queryClient])
}
