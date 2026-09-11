import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { ThemeProvider } from '@/components/theme-provider'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuthProvider } from '@/lib/auth'
import { applyCspNonce } from '@/lib/csp-nonce'
import { queryClient } from '@/lib/query-client'
import { configureZod } from '@/lib/zod-config'
import { router } from '@/routes'

// sonner's own stylesheet, which it would otherwise append to the head as a
// <style> element the production policy refuses. See vite.config.ts.
import 'sonner/dist/styles.css'
import './index.css'

// Before anything renders, so the first stylesheet a component builds already
// carries the nonce the policy asks for.
applyCspNonce()

// Before the first schema is used, which is what makes zod probe for the
// compiler the policy refuses.
configureZod()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          {/* The sidebar shows a tooltip per item when collapsed, and Radix
              requires one provider above every tooltip in the tree. */}
          <TooltipProvider delayDuration={300}>
            <RouterProvider router={router} />
          </TooltipProvider>
          <Toaster richColors position="top-center" />
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
