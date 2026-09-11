import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  categoriesCreateCategory,
  categoriesUpdateCategory,
  CategoryKind,
  type CategoryPublic,
} from '@/api'
import { Field, FormError } from '@/components/form-field'
import { SubmitButton } from '@/components/submit-button'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useCategoryTree, useInvalidateCategories } from '@/hooks/use-categories'
import { errorMessage } from '@/lib/api'
import { refill } from '@/lib/form'
import { CATEGORY_KIND_LABELS } from '@/lib/labels'
import { optionSource } from '@/lib/option-source'

const NO_PARENT = 'none'

const schema = z.object({
  name: z.string().trim().min(1, 'Give the category a name.').max(255),
  kind: z.enum(CategoryKind),
  parent_id: z.string(),
})

type Values = z.infer<typeof schema>

export function CategoryDialog({
  open,
  category,
  defaultParent,
  onOpenChange,
}: {
  open: boolean
  /** The category being edited, or null when adding one. */
  category: CategoryPublic | null
  /** Pre-selected parent, when adding from inside a group. */
  defaultParent?: CategoryPublic | null
  onOpenChange: (open: boolean) => void
}) {
  const invalidate = useInvalidateCategories()
  const isEdit = category !== null
  const categoriesQuery = useCategoryTree()
  // Without the tree there is no telling which categories could be a parent,
  // nor whether this one already has children of its own, so the picker says
  // that rather than offering a list it cannot vouch for.
  const categorySource = optionSource(categoriesQuery, 'categories')

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', kind: CategoryKind.EXPENSE, parent_id: NO_PARENT },
  })

  // Watched through `useWatch()` rather than the form's own `watch()`, which
  // hands back a function React Compiler will not memoize and skips the whole
  // component over.
  const control = form.control
  const kind = useWatch({ control, name: 'kind' })
  const parentId = useWatch({ control, name: 'parent_id' })

  useEffect(() => {
    if (!open) return
    refill(form, {
      name: category?.name ?? '',
      kind: category?.kind ?? defaultParent?.kind ?? CategoryKind.EXPENSE,
      parent_id: category?.parent_id ?? defaultParent?.id ?? NO_PARENT,
    })
  }, [open, category, defaultParent, form])

  // Only top-level categories can be parents: the tree is two levels deep.
  const parents = categorySource.options.filter(
    (node) => node.kind === kind && node.id !== category?.id,
  )

  // A category that already has subcategories cannot become one itself.
  const hasChildren = Boolean(
    categorySource.options.find((node) => node.id === category?.id)?.children?.length,
  )

  const save = useMutation({
    mutationFn: async (values: Values) => {
      const parent = values.parent_id === NO_PARENT ? null : values.parent_id

      if (category) {
        const { error } = await categoriesUpdateCategory({
          path: { category_id: category.id },
          body: { name: values.name, parent_id: parent },
        })
        if (error) throw error
        return
      }

      const { error } = await categoriesCreateCategory({
        body: { name: values.name, kind: values.kind, parent_id: parent },
      })
      if (error) throw error
    },
    onSuccess: () => {
      invalidate()
      toast.success(isEdit ? 'Category saved' : 'Category added')
      onOpenChange(false)
    },
  })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Edit ${category.name}` : 'Add a category'}</DialogTitle>
          <DialogDescription>
            Categories go two levels deep, so a subcategory cannot have subcategories of its own.
          </DialogDescription>
        </DialogHeader>

        <form
          id="category-form"
          onSubmit={form.handleSubmit((values) => save.mutate(values))}
          className="space-y-4"
          noValidate
        >
          <FormError message={save.isError ? errorMessage(save.error) : null} />

          <Field id="name" label="Name" error={form.formState.errors.name?.message}>
            {(props) => (
              <Input {...props} {...form.register('name')} placeholder="Groceries" autoFocus />
            )}
          </Field>

          {!isEdit ? (
            <Field
              id="kind"
              label="Kind"
              hint="Expense categories track money out, income categories money in."
              error={form.formState.errors.kind?.message}
            >
              {(props) => (
                <Select
                  value={kind}
                  onValueChange={(value) => {
                    form.setValue('kind', value as CategoryKind)
                    // The chosen parent may belong to the other kind now.
                    form.setValue('parent_id', NO_PARENT)
                  }}
                >
                  <SelectTrigger id={props.id} className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Object.values(CategoryKind).map((value) => (
                      <SelectItem key={value} value={value}>
                        {CATEGORY_KIND_LABELS[value]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          ) : null}

          <Field
            id="parent_id"
            label="Sits under"
            hint={
              hasChildren
                ? 'This category has subcategories, so it has to stay at the top level.'
                : 'Leave as a top-level category, or file it under one.'
            }
            error={form.formState.errors.parent_id?.message ?? categorySource.error}
          >
            {(props) => (
              <Select
                value={parentId}
                onValueChange={(value) => form.setValue('parent_id', value)}
                disabled={hasChildren || categorySource.unavailable}
              >
                <SelectTrigger id={props.id} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_PARENT}>Nothing, keep it top level</SelectItem>
                  {parents.map((parent) => (
                    <SelectItem key={parent.id} value={parent.id}>
                      {parent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
        </form>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <SubmitButton form="category-form" pending={save.isPending}>
            {isEdit ? 'Save changes' : 'Add category'}
          </SubmitButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
