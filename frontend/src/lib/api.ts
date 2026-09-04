import { client } from '@/api/client.gen'

const TOKEN_KEY = 'hydra.token'

/** Read the stored session token, if there is one. */
export function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    // Private browsing, or storage disabled. Treat it as signed out.
    return null
  }
}

/** Store the session token, or clear it when given null. */
export function writeToken(token: string | null): void {
  try {
    if (token === null) localStorage.removeItem(TOKEN_KEY)
    else localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Nothing to do: the session simply will not survive a reload.
  }
}

// The dev server proxies /api to the backend, so requests are same-origin and
// need no base URL. In production the app is served alongside the API.
client.setConfig({ baseUrl: '' })

client.interceptors.request.use((request) => {
  const token = readToken()
  if (token) request.headers.set('Authorization', `Bearer ${token}`)
  return request
})

let onUnauthenticated: (() => void) | null = null

/**
 * Register what to do when the API rejects the stored token.
 *
 * The auth provider sets this, so a token that expired between page loads
 * signs the user out rather than leaving every screen stuck on an error.
 */
export function setUnauthenticatedHandler(handler: (() => void) | null): void {
  onUnauthenticated = handler
}

client.interceptors.response.use((response) => {
  if (response.status === 401 && readToken()) onUnauthenticated?.()
  return response
})

type ValidationIssue = { loc?: (string | number)[]; msg?: string }

/**
 * Turn an API error into a sentence worth showing someone.
 *
 * The backend answers domain errors with `{"detail": "..."}`, already written
 * for a reader, and validation errors with a list of issues. Anything else is
 * unexpected, so it gets a plain fallback rather than a raw payload.
 */
export function errorMessage(
  error: unknown,
  fallback = 'Something went wrong. Try again.',
): string {
  if (typeof error === 'string') return error

  if (error && typeof error === 'object') {
    const detail = (error as { detail?: unknown }).detail

    if (typeof detail === 'string') return detail

    if (Array.isArray(detail)) {
      const messages = (detail as ValidationIssue[])
        .map((issue) => {
          const field = issue.loc?.filter((part) => part !== 'body').join(' ')
          return field ? `${field}: ${issue.msg}` : issue.msg
        })
        .filter(Boolean)
      if (messages.length) return messages.join('. ')
    }

    const message = (error as { message?: unknown }).message
    if (typeof message === 'string') return message
  }

  return fallback
}
