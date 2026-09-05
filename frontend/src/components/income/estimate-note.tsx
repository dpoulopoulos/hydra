import type { IncomeForecast } from '@/api'
import { Money } from '@/components/money'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { formatMonth } from '@/lib/month'

/** Round a rate to something a sentence can hold without looking spurious. */
function round(value: number): string {
  return value >= 10 ? String(Math.round(value)) : String(Math.round(value * 10) / 10)
}

/**
 * Where the estimate came from, folded away until somebody asks.
 *
 * An estimate nobody can explain is one nobody will plan against, so the
 * workings have to be somewhere. They are not what you came to the page for,
 * though, and left open they push the tables below the fold every time. So they
 * sit behind one line you can open.
 *
 * The wording stays generic on purpose. This is a freelancer's page, not a
 * clinic's: the same arithmetic serves a tutor, a coach or a translator, and
 * naming one trade in the copy would quietly exclude the rest.
 */
export function EstimateNote({
  forecast,
  currency,
}: {
  forecast: IncomeForecast
  currency: string
}) {
  const month = formatMonth(forecast.month, { month: 'long' })

  if (!forecast.trial_count && !forecast.new_client_session_rate) {
    return (
      <p className="text-muted-foreground text-sm">
        Nothing is booked for {month} and nobody has a standing appointment, so this is the average
        of the months before it.
      </p>
    )
  }

  const expected = forecast.expected_session_count
  const arrivals = forecast.new_client_session_rate ?? 0

  return (
    <Accordion type="single" collapsible className="w-full">
      <AccordionItem value="workings" className="border-none">
        <AccordionTrigger className="py-0 text-sm">How this is worked out</AccordionTrigger>
        <AccordionContent className="text-muted-foreground space-y-2 pt-3 text-sm">
          <p>
            {month} holds {forecast.trial_count} appointments — booked, plus the standing ones still
            to come.
            {forecast.diary_realisation_rate != null
              ? ` About ${Math.round(forecast.diary_realisation_rate * 100)} in every 100 go ahead,`
              : ' Taken at face value,'}{' '}
            {arrivals > 0
              ? `and about ${round(arrivals)} more sessions usually arrive from someone new, `
              : ''}
            {expected != null ? `so roughly ${round(expected)} sessions. ` : ''}
            About {forecast.confidence_percent ?? 95} months in 100 land inside the range.
          </p>
          {forecast.expected_client_months != null ? (
            <p>
              About {Math.round((forecast.monthly_churn_rate ?? 0) * 100)} in every 100 clients stop
              coming each month, so one stays {round(forecast.expected_client_months)} months on
              average and is worth about{' '}
              {forecast.client_lifetime_value_minor != null ? (
                <Money minor={forecast.client_lifetime_value_minor} currency={currency} />
              ) : null}{' '}
              over that time. That is why a month further off is worth less than the same diary
              nearer to hand.
            </p>
          ) : null}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}
