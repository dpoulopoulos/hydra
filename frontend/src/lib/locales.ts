import { formatMoney } from '@/lib/money'

/**
 * The locales a household may write its numbers in.
 *
 * A list rather than every tag `Intl` knows: the choice is "how should our
 * money read", and a thousand-entry picker answers a question nobody asked.
 * These cover the separators and groupings people actually run into — a dot
 * decimal, a comma decimal, a space or an apostrophe for the groups, and the
 * Indian lakh — so a household that writes numbers some way can find it.
 */
export const HOUSEHOLD_LOCALES = [
  'en-US',
  'en-GB',
  'en-IN',
  'de-DE',
  'de-CH',
  'fr-FR',
  'es-ES',
  'it-IT',
  'nl-NL',
  'pt-PT',
  'pt-BR',
  'el-GR',
  'sv-SE',
  'pl-PL',
] as const

/**
 * The amount every locale is offered written as.
 *
 * Six figures rather than four, so a locale that groups the lakh writes
 * "1,23,456.78" here and is not offered as a twin of en-US.
 */
const SAMPLE_MINOR = 12345678

/**
 * How a locale reads, as a name and an amount written its way.
 *
 * The sample carries the answer: whoever is choosing wants to know whether
 * this household's money will read "1,234.50" or "1.234,50", and the name of
 * a language is a roundabout way of saying that. The name is given in the
 * locale's own language, since that is who is looking for it.
 */
export function describeLocale(locale: string, currency: string): string {
  const name = new Intl.DisplayNames([locale], { type: 'language' }).of(locale) ?? locale
  return `${name} — ${formatMoney(SAMPLE_MINOR, currency, locale)}`
}
