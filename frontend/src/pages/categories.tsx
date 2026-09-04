import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Archive,
  ArchiveRestore,
  Lock,
  MoreHorizontal,
  Pencil,
  Plus,
  Tags,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import {
  categoriesDeleteCategory,
  categoriesUpdateCategory,
  CategoryKind,
  type CategoryPublic,
  type CategoryTreeNode,
} from '@/api'
import { CategoryDialog } from '@/components/categories/category-dialog'
import { ConfirmDialog } from '@/components/confirm-dialog'
import { EmptyState, ErrorState, LoadingRows } from '@/components/data-state'
import { PageHeader } from '@/components/layout/page-header'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useCategoryTree } from '@/hooks/use-categories'
import { errorMessage } from '@/lib/api'

export function Component() {
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<CategoryKind>(CategoryKind.EXPENSE)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [editing, setEditing] = useState<CategoryPublic | null>(null)
  const [addingUnder, setAddingUnder] = useState<CategoryPublic | null | undefined>(undefined)
  const [deleting, setDeleting] = useState<CategoryPublic | null>(null)

  const tree = useCategoryTree({ includeArchived, kind })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['categories'] })
    void queryClient.invalidateQueries({ queryKey: ['reports'] })
  }

  const setArchived = useMutation({
    mutationFn: async ({ category, archived }: { category: CategoryPublic; archived: boolean }) => {
      const { error } = await categoriesUpdateCategory({
        path: { category_id: category.id },
        body: { is_archived: archived },
      })
      if (error) throw error
      return { category, archived }
    },
    onSuccess: ({ category, archived }) => {
      invalidate()
      toast.success(
        archived
          ? `${category.name} archived${category.parent_id ? '' : ', along with anything under it'}`
          : `${category.name} restored`,
      )
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const remove = useMutation({
    mutationFn: async (category: CategoryPublic) => {
      const { error } = await categoriesDeleteCategory({ path: { category_id: category.id } })
      if (error) throw error
      return category
    },
    onSuccess: (category) => {
      invalidate()
      setDeleting(null)
      toast.success(`${category.name} deleted`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const rowActions = (category: CategoryPublic, isParent: boolean) => (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Manage ${category.name}`}>
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {isParent ? (
          <DropdownMenuItem onClick={() => setAddingUnder(category)}>
            <Plus className="size-4" />
            Add subcategory
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem disabled={category.is_system} onClick={() => setEditing(category)}>
          <Pencil className="size-4" />
          Edit
        </DropdownMenuItem>
        <DropdownMenuItem
          disabled={category.is_system}
          onClick={() => setArchived.mutate({ category, archived: category.archived_at === null })}
        >
          {category.archived_at ? (
            <>
              <ArchiveRestore className="size-4" />
              Restore
            </>
          ) : (
            <>
              <Archive className="size-4" />
              Archive
            </>
          )}
        </DropdownMenuItem>
        <DropdownMenuItem
          variant="destructive"
          disabled={category.is_system}
          onClick={() => setDeleting(category)}
        >
          <Trash2 className="size-4" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  const nameCell = (category: CategoryPublic) => (
    <span className="flex items-center gap-2">
      <span className={category.archived_at ? 'text-muted-foreground line-through' : undefined}>
        {category.name}
      </span>
      {category.is_system ? (
        <Badge variant="secondary" className="gap-1">
          <Lock className="size-3" />
          Built in
        </Badge>
      ) : null}
      {category.archived_at ? <Badge variant="outline">Archived</Badge> : null}
    </span>
  )

  return (
    <>
      <PageHeader
        title="Categories"
        description="Two levels deep. A limit on a parent covers everything filed under it."
      >
        <div className="flex items-center gap-2">
          <Label htmlFor="archived" className="text-muted-foreground text-sm font-normal">
            Show archived
          </Label>
          <Switch id="archived" checked={includeArchived} onCheckedChange={setIncludeArchived} />
        </div>
        <Button onClick={() => setAddingUnder(null)}>Add category</Button>
      </PageHeader>

      <Tabs value={kind} onValueChange={(value) => setKind(value as CategoryKind)}>
        <TabsList>
          <TabsTrigger value={CategoryKind.EXPENSE}>Money out</TabsTrigger>
          <TabsTrigger value={CategoryKind.INCOME}>Money in</TabsTrigger>
        </TabsList>
      </Tabs>

      {tree.isPending ? (
        <LoadingRows />
      ) : tree.isError ? (
        <ErrorState error={tree.error} />
      ) : tree.data.data.length === 0 ? (
        <EmptyState
          icon={Tags}
          title="No categories here"
          description="Add one to start sorting your spending."
        >
          <Button onClick={() => setAddingUnder(null)}>Add category</Button>
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {tree.data.data.map((parent: CategoryTreeNode) => {
            // children is optional on the wire, though the API always sends it.
            const children = parent.children ?? []

            return (
              <Card key={parent.id} className="gap-0 py-0">
                <CardHeader className="flex-row items-center justify-between gap-2 border-b py-3">
                  <CardTitle className="text-base">{nameCell(parent)}</CardTitle>
                  {rowActions(parent, true)}
                </CardHeader>
                <CardContent className="p-0">
                  {children.length === 0 ? (
                    <p className="text-muted-foreground px-6 py-4 text-sm">
                      Nothing under this yet.
                    </p>
                  ) : (
                    <ul className="divide-y">
                      {children.map((child) => (
                        <li
                          key={child.id}
                          className="flex items-center justify-between gap-2 py-1 pr-2 pl-6 text-sm"
                        >
                          {nameCell(child)}
                          {rowActions(child, false)}
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      <CategoryDialog
        open={addingUnder !== undefined || editing !== null}
        category={editing}
        defaultParent={addingUnder ?? null}
        onOpenChange={(open) => {
          if (!open) {
            setAddingUnder(undefined)
            setEditing(null)
          }
        }}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`Delete ${deleting?.name}?`}
        description="This only works while nothing uses it. Archive it instead to keep past reports intact."
        confirmLabel="Delete category"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </>
  )
}
