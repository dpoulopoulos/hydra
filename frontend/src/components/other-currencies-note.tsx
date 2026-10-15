import { useAccounts } from '@/hooks/use-accounts'
import { useCurrency } from '@/hooks/use-household'

/**
 * Says which accounts a figure in the household's currency leaves out.
 *
 * Reports and budgets add amounts up, and amounts in two currencies do not add
 * up, so they count only the accounts in the household's currency. Without a
 * word about it, an account in dollars would look like one with no spending.
 * Says nothing while every open account is in the household's currency.
 */
export function OtherCurrenciesNote() {
  const currency = useCurrency()
  const { data } = useAccounts()
  const others = [
    ...new Set(
      (data?.data ?? [])
        .map((account) => account.currency_code)
        .filter((code) => code !== currency),
    ),
  ].sort()

  if (others.length === 0) return null

  return (
    <p className="text-muted-foreground text-sm">
      Only accounts in {currency} are counted here. Accounts in {others.join(', ')} are left out.
    </p>
  )
}
