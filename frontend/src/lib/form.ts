import type { DefaultValues, FieldValues, Path, PathValue, UseFormReturn } from 'react-hook-form'
import type { ZodError } from 'zod'

/**
 * Fill a form with values, on a form whose render may be memoized.
 *
 * `reset()` throws away the field map by default and counts on the next render
 * calling `register()` again to build it back. React Compiler memoizes those
 * calls along with the JSX they feed, so a render it skips never repeats them:
 * the fields stay unregistered, the inputs lose the values just written to
 * them, and `handleSubmit` hands the mutation an empty form.
 *
 * `keepFieldsRef` keeps the registrations, which is what these forms meant all
 * along, but it writes the new values only onto the names React Hook Form
 * still counts as mounted, and a reset empties that set unless it is asked to
 * keep what has been typed. A second fill while the dialog stays open, such as
 * the one a late decrypt causes, would therefore reach the values but not the
 * boxes: an empty field over text the form is about to save. Writing each
 * value afterwards puts it where it can be read as well as submitted.
 *
 * A form that must not overwrite what is being typed wants `reset()` with
 * `{ keepFieldsRef: true, keepDirtyValues: true }` instead, which keeps the
 * mounted names for the same reason: see the rename field in the household
 * settings.
 */
export function refill<T extends FieldValues>(
  form: UseFormReturn<T, unknown, unknown>,
  // Taken from the form rather than from the values, so a branch handing this
  // two shapes of the same form still types against the form's own.
  values: NoInfer<DefaultValues<T>>,
): void {
  form.reset(values, { keepFieldsRef: true })
  for (const [name, value] of Object.entries(values)) {
    form.setValue(name as Path<T>, value as PathValue<T, Path<T>>)
  }
}

/**
 * Put a failed parse back onto the fields that caused it.
 *
 * A form whose values are re-parsed after submit, against something only known
 * then such as the chosen instrument's currency, can fail where the resolver
 * passed. Without this the submit handler simply returns and the button looks
 * broken.
 */
export function showIssues<T extends FieldValues>(
  form: UseFormReturn<T, unknown, unknown>,
  error: ZodError,
): void {
  for (const issue of error.issues) {
    const field = issue.path.join('.')
    // An issue with no path belongs to the form as a whole, and there is
    // nowhere to put it: setting it on a field that does not exist would hide
    // it just as surely. No schema here produces one, and if one ever does it
    // needs a place on the form to show rather than a silent drop.
    if (field) form.setError(field as Path<T>, { type: 'manual', message: issue.message })
  }
}
