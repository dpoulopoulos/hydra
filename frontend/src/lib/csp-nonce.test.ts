import { getNonce, setNonce } from 'get-nonce'
import { afterEach, describe, expect, it } from 'vitest'

import { applyCspNonce } from '@/lib/csp-nonce'

function meta(nonce: string) {
  document.head.innerHTML = `<meta property="csp-nonce" nonce="${nonce}">`
}

afterEach(() => {
  document.head.innerHTML = ''
  setNonce(undefined as unknown as string)
})

describe('applyCspNonce', () => {
  it('passes the nonce in the page to the libraries that inject stylesheets', () => {
    meta('r4nd0m')

    applyCspNonce()

    expect(getNonce()).toBe('r4nd0m')
  })

  it('ignores the server side placeholder left in the page in development', () => {
    meta('{{placeholder `http.request.uuid`}}')

    applyCspNonce()

    expect(getNonce()).toBeUndefined()
  })

  it('does nothing when the page carries no nonce', () => {
    applyCspNonce()

    expect(getNonce()).toBeUndefined()
  })
})
