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

/**
 * The status of a failed request, when the request reached the server.
 *
 * The generated client throws the response body, which says nothing about the
 * status. Whether to retry, and whether a failure means the session is over,
 * are both questions about the status: a 401 is a rejection to accept, a 502 is
 * a hiccup to try again. So it is stamped onto the error on its way out.
 */
export type ApiError = { status?: number }

/**
 * The status of a failed request, or undefined when it never got one.
 *
 * A request that did not reach the server throws something with no status on
 * it at all, and not always an object: read it without assuming either.
 */
export function errorStatus(error: unknown): number | undefined {
  return typeof error === 'object' && error !== null ? (error as ApiError).status : undefined
}

/** The two 4xx statuses that ask for another go rather than settling the matter. */
const RETRY_ANYWAY = new Set([408, 429])

/**
 * Whether a failed request is the server's answer, rather than a request that
 * never got one.
 *
 * A 4xx is considered, so repeating it only repeats the rejection, and on the
 * session check it is a session that is over: a 401 for a token the server
 * will not take, a 403 for an account that is no longer active, a 404 for one
 * that is gone. Bar a timeout and a rate limit, which are the server asking to
 * be asked again. Anything else — a 502 from the proxy while the backend
 * restarts, a connection that dropped — may well pass a second later.
 */
export function isRejection(error: unknown): boolean {
  const status = errorStatus(error)
  return status !== undefined && status >= 400 && status < 500 && !RETRY_ANYWAY.has(status)
}

client.interceptors.error.use((error, response) => {
  // A 2xx whose body could not be parsed lands here too. Its status is not a
  // rejection and nothing should read it as one, so it is left unstamped and
  // the failure stays what it is: a body the client could not make sense of.
  if (!response || response.ok) return error
  // A body the server did not write as JSON — a proxy's HTML error page, say —
  // is not worth showing anyone, so only the status is kept.
  if (!error || typeof error !== 'object') return { status: response.status }
  return Object.assign(error, { status: response.status })
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
