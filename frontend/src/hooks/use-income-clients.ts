import { useQuery } from '@tanstack/react-query'

import { incomeListClients, type IncomeClientPublic } from '@/api'

/** The most the API will return in one request. */
const PAGE = 200

/**
 * How many pages to walk before giving up.
 *
 * A bound rather than a while-loop, so a count that disagrees with the rows it
 * describes cannot spin here for ever.
 */
const MAX_PAGES = 20

/**
 * Every client of the practice, for the pickers and for the name lookup.
 *
 * Fetched whole rather than a page at a time, because the names come back
 * encrypted and the page decrypts them: the server can neither search nor sort
 * by name, so filtering has to happen here with all of them to hand. It is
 * also the lookup behind every session row, and a name is not optional because
 * its client happens to sit past a page boundary.
 *
 * So it pages through to the end. The API caps a request at 200, which a busy
 * practice will pass, and stopping there would leave those rows showing a dash
 * with nothing to say why.
 *
 * There is still a bound, because an unbounded walk is not something to put on
 * a page load. If it is ever reached the result says so through `isComplete`,
 * so the truncation is reported rather than silently producing rows with no
 * names against them.
 */
export function useIncomeClients(includeArchived = false) {
  return useQuery({
    queryKey: ['income-clients', { includeArchived }],
    queryFn: async () => {
      const rows: IncomeClientPublic[] = []
      let count = 0

      for (let page = 0; page < MAX_PAGES; page += 1) {
        const { data, error } = await incomeListClients({
          query: {
            ...(includeArchived ? {} : { is_archived: false }),
            skip: page * PAGE,
            limit: PAGE,
          },
        })
        if (error) throw error

        rows.push(...data.data)
        count = data.count

        if (rows.length >= count || data.data.length === 0) break
      }

      return { data: rows, count, isComplete: rows.length >= count }
    },
    staleTime: 60_000,
  })
}
