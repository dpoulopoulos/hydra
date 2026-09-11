import { z } from 'zod'

/**
 * Tells zod not to compile its validators.
 *
 * zod builds a fast parser for an object schema with `new Function`, and probes
 * for it the first time a schema is used. The production policy allows no eval
 * (`script-src 'self'`, see Caddyfile), so the browser refuses the probe. zod
 * swallows the refusal and validates the slow way, which is why nothing is
 * visibly broken, but the browser still reports a violation for it -- on the
 * sign-in form, and on every other form the app shows.
 *
 * Setting this is what zod asks for in an environment with such a policy: it
 * skips the probe, and the parsing is the same parsing the fallback already
 * did. Forms are a few fields each, so the compiled parser buys nothing here
 * that is worth a violation report.
 */
export function configureZod(): void {
  z.config({ jitless: true })
}
