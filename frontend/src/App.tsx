import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

export default function App() {
  return (
    <main className="bg-background flex min-h-svh items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>hydra</CardTitle>
          <CardDescription>
            Track spending, set monthly budgets, and see where the money went.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center gap-3">
          <Button>Primary</Button>
          <span className="text-positive font-medium tabular-nums">+2 500,00</span>
          <span className="text-negative font-medium tabular-nums">-242,50</span>
        </CardContent>
      </Card>
    </main>
  )
}
