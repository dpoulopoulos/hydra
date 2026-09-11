import { render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { describe, expect, it } from 'vitest'

import { refill } from '@/lib/form'

type Values = { name: string; note: string }

/**
 * A form that registers its fields exactly once.
 *
 * This is what React Compiler makes of a dialog: the JSX is built on the first
 * render and handed back unchanged afterwards, so the `register()` calls
 * inside it never run again. Anything the form needs a second render to put
 * right therefore never happens.
 */
function OnceRegistered({ values }: { values: Values }) {
  const form = useForm<Values>({ defaultValues: { name: '', note: '' } })
  const [fields] = useState(() => (
    <>
      <input aria-label="Name" {...form.register('name')} />
      <input aria-label="Note" {...form.register('note')} />
    </>
  ))

  useEffect(() => {
    refill(form, values)
  }, [form, values])

  return <form>{fields}</form>
}

describe('refill', () => {
  it('writes the newest values onto the fields, however often it is called', async () => {
    const { rerender } = render(<OnceRegistered values={{ name: '', note: '' }} />)

    // The second fill is the one that catches a form out: a dialog left open
    // while a decrypt, or a fetch, lands the values it was waiting for.
    rerender(<OnceRegistered values={{ name: 'Anna', note: 'Fridays' }} />)

    expect(await screen.findByLabelText('Name')).toHaveValue('Anna')
    expect(screen.getByLabelText('Note')).toHaveValue('Fridays')
  })
})
