import type { FieldValues, Path, UseFormReturn } from 'react-hook-form'
import type { ZodError } from 'zod'

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
