import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // src/api is generated from the backend's OpenAPI schema.
  globalIgnores(['dist', 'src/api']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // Components under ui/ and the hooks that ship with them are vendored from
    // shadcn/ui. `shadcn add` overwrites them, so patching them here would be
    // undone on the next update. Two of its house patterns trip our rules:
    // exporting a `cva` variants object beside the component, and priming
    // state from a media query inside an effect.
    files: ['src/components/ui/**/*.{ts,tsx}', 'src/hooks/use-mobile.ts'],
    rules: {
      'react-refresh/only-export-components': 'off',
      'react-hooks/set-state-in-effect': 'off',
    },
  },
])
