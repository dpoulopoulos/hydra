import { vi } from 'vitest'

import type { AuthValue } from '@/lib/auth-context'

/**
 * A session to hand a component under test: signed out, unless said otherwise.
 *
 * Shared because the context is read by every screen behind the gate, and a
 * test that only cares whether someone is signed in should not have to be
 * edited each time the session gains a field.
 */
export function session(value: Partial<AuthValue> = {}): AuthValue {
  return {
    user: null,
    isLoading: false,
    isAuthenticated: false,
    isUnauthenticated: false,
    error: null,
    retry: vi.fn(),
    isRetrying: false,
    signIn: vi.fn(),
    signOut: vi.fn(),
    ...value,
  }
}
