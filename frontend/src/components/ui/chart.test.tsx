import { render } from '@testing-library/react'
import { Bar, BarChart } from 'recharts'
import { describe, expect, it } from 'vitest'

import { ChartContainer, type ChartConfig } from '@/components/ui/chart'

// The colours a chart's series were given have to reach the marks as
// `--color-<key>`. shadcn's wrapper ships them in a <style> element, which the
// production policy in frontend/Caddyfile forbids: `style-src-elem 'self'`
// allows no inline stylesheet, injected by this app or by an attacker. The
// values belong on the container's style attribute instead.
describe('ChartContainer', () => {
  const config: ChartConfig = {
    income: { label: 'Money in', color: 'var(--positive)' },
    expense: { label: 'Money out', color: 'var(--negative)' },
  }

  function renderChart(props?: { style?: React.CSSProperties }) {
    return render(
      <ChartContainer config={config} {...props}>
        <BarChart data={[]}>
          <Bar dataKey="income" />
        </BarChart>
      </ChartContainer>,
    )
  }

  it('renders no stylesheet of its own', () => {
    const { container } = renderChart()

    expect(container.querySelector('style')).toBeNull()
    expect(document.head.querySelector('style')).toBeNull()
  })

  it('sets each configured colour as a custom property on the container', () => {
    const { container } = renderChart()

    const chart = container.querySelector<HTMLElement>('[data-slot="chart"]')

    expect(chart?.style.getPropertyValue('--color-income')).toBe('var(--positive)')
    expect(chart?.style.getPropertyValue('--color-expense')).toBe('var(--negative)')
  })

  it('keeps the styles the caller passed', () => {
    const { container } = renderChart({ style: { height: 240 } })

    const chart = container.querySelector<HTMLElement>('[data-slot="chart"]')

    expect(chart?.style.height).toBe('240px')
    expect(chart?.style.getPropertyValue('--color-income')).toBe('var(--positive)')
  })
})
