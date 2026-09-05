import { createContext } from 'react'

/** Whether the client names can be read right now. */
export type VaultStatus =
  /** Still asking the server whether a PIN was ever set up. */
  | 'loading'
  /** No PIN has been set up. There is nothing to unlock yet.  */
  | 'absent'
  /** A PIN exists and has not been entered in this browser session. */
  | 'locked'
  /** The key is held in memory and names can be read. */
  | 'unlocked'

export type VaultValue = {
  status: VaultStatus
  /** Open the vault for this browser session. Rejects on a wrong PIN. */
  unlock: (pin: string) => Promise<void>
  /** Create the vault for the first time. */
  setUp: (pin: string) => Promise<void>
  /** Re-wrap the key under a new PIN. Every stored name stays readable. */
  changePin: (pin: string) => Promise<void>
  /** Forget the key. The names are unreadable until the PIN is entered again. */
  lock: () => void
  /** Encrypt a name before it is sent. Throws while locked. */
  encrypt: (text: string) => Promise<string>
  /** Decrypt a stored name. Returns null when locked or unreadable. */
  decrypt: (ciphertext: string) => Promise<string | null>
}

// Split from the provider so the module that exports the component exports
// nothing else, which is what fast refresh needs.
export const VaultContext = createContext<VaultValue | null>(null)
