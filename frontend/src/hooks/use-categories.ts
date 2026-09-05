import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback } from 'react'

import { categoriesGetCategoryTree, categoriesListCategories, type CategoryKind } from '@/api'

/**
 * Drop every cache a category edit touches.
 *
 * Reports embed the category *name*, not just its id, so a rename has to clear
 * the reports as well, or the charts and the budget bars keep the old name
 * until their entries go stale on their own.
 */
export function useInvalidateCategories() {
  const queryClient = useQueryClient()

  return useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['categories'] })
    void queryClient.invalidateQueries({ queryKey: ['reports'] })
  }, [queryClient])
}

/** The category tree, for pickers and for the categories page. */
export function useCategoryTree(options?: { includeArchived?: boolean; kind?: CategoryKind }) {
  return useQuery({
    queryKey: ['categories', 'tree', options],
    queryFn: async () => {
      const { data, error } = await categoriesGetCategoryTree({
        query: { include_archived: options?.includeArchived ?? false, kind: options?.kind ?? null },
      })
      if (error) throw error
      return data
    },
    staleTime: 5 * 60_000,
  })
}

/** The flat category list, for looking a name up by id. */
export function useCategories(options?: { includeArchived?: boolean; kind?: CategoryKind }) {
  return useQuery({
    queryKey: ['categories', 'flat', options],
    queryFn: async () => {
      const { data, error } = await categoriesListCategories({
        query: { include_archived: options?.includeArchived ?? true, kind: options?.kind ?? null },
      })
      if (error) throw error
      return data
    },
    staleTime: 5 * 60_000,
  })
}
