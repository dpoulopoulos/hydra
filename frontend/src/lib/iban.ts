/**
 * IBAN helpers.
 *
 * The API is the authority on what a valid IBAN is, and it stores one compact
 * and upper case. The same check runs here so a typo is answered next to the
 * field, rather than by a round trip that reports it in the API's own words.
 */

const SHAPE = /^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$/

/** Split an IBAN into groups of four, the way banks print it. */
export function formatIban(iban: string): string {
  return iban.replace(/(.{4})/g, '$1 ').trim()
}

/** Strip what a user typed back to the compact form the API expects. */
export function compactIban(value: string): string {
  return value.replace(/\s/g, '').toUpperCase()
}

/**
 * Check an IBAN, spacing and case already stripped.
 *
 * The check digits are what makes this worth doing: they catch a mistyped or
 * swapped character that a length check would let through. The account number
 * moves to the front, every letter becomes its position in the alphabet plus
 * nine, and a valid IBAN leaves a remainder of one modulo 97.
 */
export function isValidIban(compact: string): boolean {
  if (!SHAPE.test(compact)) return false

  const rearranged = compact.slice(4) + compact.slice(0, 4)
  // The number is far past what a JavaScript number holds exactly, so the
  // remainder is taken a few digits at a time instead of all at once.
  let remainder = 0
  for (const character of rearranged) {
    remainder = (remainder * (character >= 'A' ? 100 : 10) + parseInt(character, 36)) % 97
  }

  return remainder === 1
}
