import { useQuery } from '@tanstack/react-query'

import { categoriesGetCategoryTree, categoriesListCategories, type CategoryKind } from '@/api'

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
