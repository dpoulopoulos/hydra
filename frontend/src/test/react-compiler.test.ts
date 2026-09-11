import * as babel from '@babel/core'
import { reactCompilerPreset } from '@vitejs/plugin-react'
import { glob, readFile } from 'node:fs/promises'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Every component the app ships, compiled the way the build compiles it.
 *
 * React Compiler is not all-or-nothing: it gives up on a component it cannot
 * reason about, says so, and leaves it as written. That is a line in a build
 * log nobody reads, so a component can quietly stop being memoized without
 * anything failing. Nine of them sat like that for as long as their forms
 * watched fields through React Hook Form's `watch()`.
 *
 * This reads the events the compiler logs rather than the code it returns: a
 * bailout is reported, not thrown, and the file still comes back looking
 * compiled.
 */

const root = path.resolve(import.meta.dirname, '..')

/**
 * The components the compiler cannot take on yet, and why.
 *
 * Every one of these is a piece of syntax the compiler has not learnt rather
 * than anything the file is doing wrong, so the list shrinks as the compiler
 * grows rather than as the app is rewritten. It is checked both ways: an entry
 * that starts compiling has to be removed from here.
 */
const NOT_YET_COMPILED: Record<string, string> = {
  // Throwing from inside a try/catch.
  'components/copy-button.tsx': 'BuildHIR::lowerStatement ThrowStatement inside of try/catch',
  // A conditional inside a try/catch, in both of these.
  'components/income/pin-dialog.tsx': 'value blocks within a try/catch statement',
  'pages/auth/login.tsx': 'value blocks within a try/catch statement',
  // Vendored from shadcn/ui, so not ours to rewrite.
  'components/ui/calendar.tsx': 'tagged template where the cooked value differs from the raw one',
}

/** The files the compiler gave up on, relative to `src`. */
async function filesTheCompilerSkipped() {
  const skipped = new Set<string>()

  for await (const file of glob(`${root}/**/*.tsx`)) {
    // The tests render the components; they are not shipped with them.
    if (file.endsWith('.test.tsx')) continue

    await babel.transformAsync(await readFile(file, 'utf8'), {
      filename: file,
      babelrc: false,
      configFile: false,
      parserOpts: { plugins: ['typescript', 'jsx'] },
      // The same preset the Vite config hands to Babel, unwrapped from the
      // plugin's own wrapper, with somewhere to report what it found.
      presets: [
        reactCompilerPreset({
          logger: {
            logEvent: (_filename, event) => {
              if (event.kind === 'CompileError') skipped.add(path.relative(root, file))
            },
          },
        }).preset,
      ],
    })
  }

  return skipped
}

describe('React Compiler', () => {
  it('memoizes every component but the ones it cannot read yet', async () => {
    const skipped = await filesTheCompilerSkipped()

    expect([...skipped].filter((file) => !(file in NOT_YET_COMPILED)).sort()).toEqual([])
    expect(
      Object.keys(NOT_YET_COMPILED)
        .filter((file) => !skipped.has(file))
        .sort(),
    ).toEqual([])
  }, 120_000)
})
