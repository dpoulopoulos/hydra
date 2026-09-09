import { errorMessage } from '@/lib/api'

/** What a picker can offer, and why it cannot when it has nothing. */
export type OptionSource<T> = {
  /** The options to render. Empty while the list is on its way, or lost. */
  options: T[]
  /** True when the list was asked for and refused, so waiting will not help. */
  unavailable: boolean
  /** Why the picker is empty, written for the reader. Undefined when it is not. */
  error?: string
}

/**
 * Read a query the way a picker needs it.
 *
 * A select whose options come from a query has three states, not two: on its
 * way, loaded, and refused. The `?? []` default collapses the third into "there
 * are none", which is the one thing a picker must never say silently: a form
 * control that offers nothing looks like a household with no accounts rather
 * than a request that failed, and the user is left unable to act with no reason
 * given.
 *
 * A failed *refetch* is not the same thing. The list already came back once, so
 * it is still the truth as far as anyone knows, and the picker keeps offering
 * it rather than throwing away a working form over a background request.
 */
export function optionSource<T>(
  query: { data?: { data: T[] } | undefined; isError: boolean; error: unknown },
  /** The plural the message names, as the user would: "accounts", "categories". */
  noun: string,
): OptionSource<T> {
  const options = query.data?.data
  if (options) return { options, unavailable: false }
  if (!query.isError) return { options: [], unavailable: false }

  return {
    options: [],
    unavailable: true,
    error: `Could not load your ${noun}. ${errorMessage(query.error, 'Try again in a moment.')}`,
  }
}
