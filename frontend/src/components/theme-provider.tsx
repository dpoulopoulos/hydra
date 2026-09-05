import { getNonce } from 'get-nonce'
import { ThemeProvider as NextThemeProvider } from 'next-themes'
import type { ReactNode } from 'react'

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemeProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      // Switching theme suppresses transitions through a stylesheet built on
      // the spot, which the production policy takes only with the page's own
      // nonce. See src/lib/csp-nonce.ts.
      nonce={getNonce()}
      disableTransitionOnChange
    >
      {children}
    </NextThemeProvider>
  )
}
