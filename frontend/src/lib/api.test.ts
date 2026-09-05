import { afterEach, describe, expect, it } from 'vitest'

import { client } from '@/api/client.gen'
import { errorMessage, isRejection } from '@/lib/api'

/**
 * Answer the next request with this response, without touching the network.
 *
 * The app leaves the base URL empty, because the browser resolves a relative
 * URL against the page. `Request` outside a browser will not, so the tests give
 * it an origin to resolve against.
 */
function respondWith(status: number, body: string, contentType = 'application/json') {
  client.setConfig({
    baseUrl: 'http://localhost',
    fetch: async () => new Response(body, { status, headers: { 'Content-Type': contentType } }),
  })
}

afterEach(() => {
  client.setConfig({ baseUrl: '', fetch: globalThis.fetch })
})

describe('failed requests', () => {
  it('carries the status of a rejection', async () => {
    respondWith(401, JSON.stringify({ detail: 'Not authenticated' }))

    const { error } = await client.get({ url: '/api/v1/users/me' })

    expect(error).toMatchObject({ detail: 'Not authenticated', status: 401 })
  })

  it('carries the status of a body that is not JSON', async () => {
    respondWith(502, '<html>Bad Gateway</html>', 'text/html')

    const { error } = await client.get({ url: '/api/v1/users/me' })

    expect(error).toMatchObject({ status: 502 })
  })

  it('does not stamp a status on an answer that merely would not parse', async () => {
    respondWith(200, 'not json at all')

    const { error } = await client.get({ url: '/api/v1/users/me' })

    expect(error).toBeDefined()
    expect(error).not.toHaveProperty('status')
  })

  it('leaves the message of a rejection readable', async () => {
    respondWith(400, JSON.stringify({ detail: 'That account already exists.' }))

    const { error } = await client.get({ url: '/api/v1/users/me' })

    expect(errorMessage(error)).toBe('That account already exists.')
  })
})

describe('a rejection, as told from a request that got no answer', () => {
  it('reads any 4xx as the answer the server chose', () => {
    // /users/me answers 401 for a token it will not take, 403 for an account
    // that is no longer active and 404 for a record that is gone.
    expect(isRejection({ status: 401 })).toBe(true)
    expect(isRejection({ status: 403 })).toBe(true)
    expect(isRejection({ status: 404 })).toBe(true)
  })

  it('reads a timeout and a rate limit as the server asking to be asked again', () => {
    expect(isRejection({ status: 408 })).toBe(false)
    expect(isRejection({ status: 429 })).toBe(false)
  })

  it('reads a failure the server did not choose as no answer at all', () => {
    expect(isRejection({ status: 500 })).toBe(false)
    expect(isRejection({ status: 502 })).toBe(false)
  })

  it('reads a request that never reached the server as no answer at all', () => {
    expect(isRejection(new TypeError('Failed to fetch'))).toBe(false)
    expect(isRejection('network down')).toBe(false)
    expect(isRejection(null)).toBe(false)
    expect(isRejection(undefined)).toBe(false)
  })
})
