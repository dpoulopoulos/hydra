import { z } from 'zod'

import {
  numberGrouping,
  numberSeparators,
  toMinor,
  type NumberGrouping,
  type NumberSeparators,
} from '@/lib/money'

/**
 * Which of "." and "," the string uses as its decimal point, most likely
 * first, or `null` for "every separator in it is a group mark".
 *
 * "." and "," are each both a decimal point and a thousands separator,
 * depending on where you live and where in the number they sit, so the
 * question rarely has one answer from the characters alone. Most strings are
 * settled by shape: the decimal point comes last, only a group mark repeats,
 * and neither "42,5" nor a leading separator can be grouping. What is left,
 * one separator with a whole group's worth of digits after it, is the
 * genuinely ambiguous "1,200", and only the locale can say what the writer
 * meant.
 */
function decimalCandidates(
  text: string,
  separators: NumberSeparators,
  grouping: NumberGrouping,
): (string | null)[] {
  const lastDot = text.lastIndexOf('.')
  const lastComma = text.lastIndexOf(',')

  // Both characters are in there, so each has a job: the last one read is the
  // decimal point, whichever character it is, and the other is the group mark.
  if (lastDot >= 0 && lastComma >= 0) return [lastDot > lastComma ? '.' : ',']

  const candidate = lastDot >= 0 ? '.' : lastComma >= 0 ? ',' : null
  if (candidate === null) return [null]

  // A number has one decimal point but any number of group marks.
  if (text.split(candidate).length > 2) return [null]

  const index = text.indexOf(candidate)
  // Grouping cannot lead, so ",50" is half a unit.
  if (index === 0) return [candidate]
  // "42,5" and "1,23456" leave the wrong number of digits for a group.
  if (text.length - index - 1 !== grouping.primary) return [candidate]

  // "1,200". Read it the way the locale writes it back to the reader, and if
  // the digits do not group cleanly, as a decimal point after all.
  return candidate === separators.decimal ? [candidate] : [null, candidate]
}

/** Whether groups of digits are the sizes a grouping puts them in. */
function groupsFit(groups: string[], { primary, secondary }: NumberGrouping): boolean {
  if (groups[0].length > secondary) return false

  const rest = groups.slice(1)
  return rest.every(
    (digits, index) => digits.length === (index === rest.length - 1 ? primary : secondary),
  )
}

/**
 * Drop the group marks from a number's integer part, or `null` if they are
 * not where grouping puts them, as in "1,23,456" read as en-US.
 *
 * Three digits to a group is the common shape but not the only one: en-IN
 * groups the lakh, writing 1234567 as "12,34,567", so the locale's own
 * grouping is taken as well. Plain three-digit groups are read everywhere,
 * because they carry the same digits whoever wrote them.
 */
function ungroup(text: string, group: string, grouping: NumberGrouping): string | null {
  if (!text.includes(group)) return /^\d*$/.test(text) ? text : null

  const groups = text.split(group)
  // A grouped number runs past its first full group, so its leading group is
  // never padded: "0,500" is half a unit written oddly, not five hundred.
  if (!/^[1-9]\d*$/.test(groups[0])) return null
  if (!groups.slice(1).every((digits) => /^\d+$/.test(digits))) return null

  const fits = groupsFit(groups, grouping) || groupsFit(groups, { primary: 3, secondary: 3 })
  return fits ? groups.join('') : null
}

/** Read the string as a number, given which character is its decimal point. */
function readMajor(text: string, decimal: string | null, grouping: NumberGrouping): number | null {
  const at = decimal === null ? -1 : text.lastIndexOf(decimal)
  const fraction = at < 0 ? '' : text.slice(at + 1)
  const integer = at < 0 ? text : text.slice(0, at)

  // Whatever is not the decimal point groups, and with no decimal point at
  // all the one character present is the group mark.
  const group = decimal === '.' ? ',' : decimal === ',' ? '.' : integer.includes(',') ? ',' : '.'

  if (!/^\d*$/.test(fraction)) return null
  const digits = ungroup(integer, group, grouping)
  if (digits === null) return null
  if (digits === '' && fraction === '') return null

  return Number(`${digits || '0'}.${fraction || '0'}`)
}

/**
 * Read a typed amount as major units, or `null` if it is not a number.
 *
 * People type "42.50" or "42,50" depending on their keyboard and locale, and
 * they type the thousands separator the app formats amounts with, so "1,200"
 * has to mean twelve hundred where the reader was shown "€1,200.00" and one
 * and a fifth where they were shown "€1,20". Both separators are read in
 * whichever role their position and the locale give them.
 */
export function parseMajor(value: string, locale?: string): number | null {
  const { decimal, group } = numberSeparators(locale)
  const grouping = numberGrouping(locale)

  // Grouping written with a space, as fr-FR does, or with an apostrophe, as
  // de-CH does, says nothing about the decimal point, so it goes first.
  let text = value.replace(/\s/g, '')
  if (group !== '.' && group !== ',') text = text.split(group).join('')

  // A decimal point that is neither "." nor "," - ar-EG and fa-IR write "٫" -
  // can only be a decimal point, since it is not the character anything groups
  // with. Read it as the dot the rules below are written in, which both accepts
  // it and leaves a typed "." to be read as this locale's own decimal point.
  const separators: NumberSeparators =
    decimal === '.' || decimal === ',' ? { decimal, group } : { decimal: '.', group }
  if (separators.decimal !== decimal) text = text.split(decimal).join('.')

  if (!/^[\d.,]+$/.test(text)) return null

  for (const candidate of decimalCandidates(text, separators, grouping)) {
    const major = readMajor(text, candidate, grouping)
    if (major !== null) return major
  }
  return null
}

/**
 * The largest amount a form accepts, in minor units.
 *
 * The API caps every amount far above this, but past Number.MAX_SAFE_INTEGER a
 * JavaScript number no longer holds an exact integer, so what would be sent is
 * not what was typed. Bounding it here keeps an absurd amount an inline message
 * on the field rather than a rejected request.
 */
export const MAX_AMOUNT_MINOR = Number.MAX_SAFE_INTEGER

/**
 * A typed amount, as minor units.
 *
 * The string is read by `parseMajor`, so a field takes an amount written the
 * way the app writes it back, and the result is the integer the API takes.
 *
 * The currency is a parameter rather than an option with a default: how many
 * minor units a typed amount stands for is a property of the currency, and a
 * default would let a form render in one currency and parse in another
 * without anything saying so.
 */
export function amountSchema(currency: string, options?: { allowZero?: boolean; locale?: string }) {
  const min = options?.allowZero ? 0 : 1

  return z
    .string()
    .trim()
    .min(1, 'Enter an amount.')
    .transform((value, ctx) => {
      const major = parseMajor(value, options?.locale)
      if (major === null) {
        ctx.addIssue({ code: 'custom', message: 'Enter a number.' })
        return z.NEVER
      }
      return toMinor(major, currency)
    })
    .refine((minor) => Number.isFinite(minor) && minor >= min, {
      message: options?.allowZero ? 'Enter zero or more.' : 'Enter an amount above zero.',
    })
    .refine((minor) => minor <= MAX_AMOUNT_MINOR, { message: 'Enter a smaller amount.' })
}

/**
 * What a field holds so far, as minor units, or null while it does not read as
 * an amount yet.
 *
 * A preview sentence reads the field as it is typed, before the resolver has
 * had anything to say about it, so it has to make the same sense of "1 000" or
 * "42,50" that the saved value does. Reading it through the same schema is what
 * keeps the two in step; a `Number()` of its own drifts the moment either one
 * learns a new separator.
 *
 * Zero is a value, not a blank: a caller that has nothing to say about zero
 * decides that for itself.
 *
 * The locale is the one the field was filled in for, so the preview reads
 * "1.200" the way the household writes it rather than the way the browser
 * happens to.
 */
export function previewMinor(
  value: string | undefined,
  currency: string,
  locale?: string,
): number | null {
  const parsed = amountSchema(currency, { allowZero: true, locale }).safeParse(value ?? '')
  return parsed.success ? parsed.data : null
}
