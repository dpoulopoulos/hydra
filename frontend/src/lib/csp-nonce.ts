import { setNonce } from 'get-nonce'

/**
 * Hands the nonce the server put in the page to the libraries that build a
 * <style> element while they run.
 *
 * The production policy honours no inline stylesheet (`style-src-elem 'self'`,
 * see Caddyfile), which on its own would refuse the scroll lock Radix applies
 * behind a dialog along with anything an attacker managed to inject. Caddy
 * renders a fresh nonce into the meta tag and names that same value in the
 * header on every response, so a stylesheet the app builds carries it and one
 * arriving from anywhere else cannot.
 *
 * Nothing renders the page in development, where the meta tag still holds
 * Caddy's placeholder and there is no policy to satisfy, so it is left alone.
 */
export function applyCspNonce(): void {
  const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce

  if (nonce && !nonce.includes('{')) {
    setNonce(nonce)
  }
}
