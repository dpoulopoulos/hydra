// Walks the built app in a real browser and fails on a content security
// policy violation.
//
// Run by test-csp.sh, which builds the app and serves it with the production
// Caddyfile and a stub backend; the address it is serving on is the only
// argument. A run on its own against anything else works the same way.
//
// What this is for: three of the app's dependencies build a stylesheet while
// they run -- Radix's scroll lock, sonner's toaster, next-themes -- and
// `style-src-elem` honours one only with the nonce the server put in the page.
// A release that stops reading that nonce, or a new dependency that never
// asked for one, breaks a screen in production and nothing else notices. The
// browser notices: it refuses the stylesheet and says so.
//
// So the walk visits the screens those three show up on, and reports every
// violation the browser raised along the way, plus anything it logged as an
// error. Each step also asserts something it should be able to see, because a
// walk that never arrived would otherwise pass with no violations at all.

import { chromium } from 'playwright'

const base = process.argv[2]

if (!base) {
  console.error('usage: node csp-walk.mjs <base-url>')
  process.exit(2)
}

let failures = 0

/** Reports one expectation, and remembers a failure without stopping. */
function check(what, expected, actual) {
  if (expected === actual) {
    console.log(`ok   - ${what}`)
  } else {
    console.log(`FAIL - ${what}: expected '${expected}', got '${actual}'`)
    failures += 1
  }
}

// Everything the page logged as an error, collected for the whole walk and
// reported at the end, so one broken step does not hide what the rest would
// have found.
const errors = []

const browser = await chromium.launch()
// A viewport a desktop layout fits in: the sidebar collapses on a narrow one,
// which would put the screens the walk visits behind a menu.
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })

// Before anything the page loads, so a stylesheet refused during startup is
// caught too. The event is the browser's own report of a refusal, and carries
// which directive did the refusing.
await context.addInitScript(() => {
  window.__cspViolations = []
  document.addEventListener('securitypolicyviolation', (event) => {
    window.__cspViolations.push({
      directive: event.effectiveDirective,
      blocked: event.blockedURI,
      // Where the refused thing came from, which is the only way to tell
      // which dependency built it.
      source: `${event.sourceFile}:${event.lineNumber}`,
    })
  })
})

const page = await context.newPage()

page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})
page.on('pageerror', (error) => errors.push(String(error)))

/**
 * A short account of what a run ran into.
 *
 * The same refusal repeats -- once per render, once per screen -- and the same
 * console message with it, so what is reported is each distinct one, and only
 * the first few of those. A check says what is wrong; the browser is where the
 * rest of it is.
 */
function summarise(entries) {
  const distinct = [...new Set(entries)]
  const shown = distinct.slice(0, 3).join(' | ')
  return distinct.length > 3 ? `${shown} | and ${distinct.length - 3} more` : shown
}

/** What a violation is called in a report: the rule, and what tripped it. */
function describe(violation) {
  return `${violation.directive} ${violation.blocked} (${violation.source})`
}

/**
 * The violations the page has raised since this was last called, and clears
 * them: each step reports its own, so a refusal is named where it happened.
 */
async function newViolations() {
  return page.evaluate(() => {
    const raised = window.__cspViolations ?? []
    window.__cspViolations = []
    return raised
  })
}

/** Runs one step of the walk, and reports what the policy refused during it. */
async function step(what, body) {
  await body()
  const raised = await newViolations()
  check(
    `${what}: nothing was refused by the policy`,
    'none',
    raised.length === 0 ? 'none' : summarise(raised.map(describe)),
  )
}

try {
  // The sign-in screen, which is all a visitor with no session is shown.
  await step('the sign-in screen', async () => {
    await page.goto(`${base}/login`, { waitUntil: 'networkidle' })
    check('the sign-in screen is shown', true, await page.getByLabel('Email').isVisible())
  })

  // The nonce the policy names has to reach the app, which reads it out of the
  // meta tag. A page rendered without it would still pass the walk while every
  // stylesheet the app builds was refused, so it is asserted directly.
  const nonce = await page.evaluate(
    () => document.querySelector('meta[property="csp-nonce"]')?.nonce ?? '',
  )
  check(
    'the entry page carries the nonce the policy names',
    'a uuid',
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(nonce)
      ? 'a uuid'
      : `'${nonce}'`,
  )

  // What a green run is worth depends on the browser actually enforcing the
  // policy: if it were not, nothing below could fail. So a stylesheet without
  // the nonce is appended on purpose, and has to be refused.
  //
  // On a page of its own, which is then thrown away: the refusal is reported
  // like any other, and counting a refusal the walk asked for would be the one
  // way to fail a run that found nothing wrong.
  const probe = await context.newPage()
  await probe.goto(`${base}/login`)
  const refused = await probe.evaluate(() => {
    const style = document.createElement('style')
    style.textContent = 'html { --csp-walk-probe: applied }'
    document.head.append(style)
    const applied = getComputedStyle(document.documentElement).getPropertyValue('--csp-walk-probe')
    style.remove()
    return applied.trim() === '' ? 'refused' : 'applied'
  })
  await probe.close()
  check('a stylesheet without the nonce is refused', 'refused', refused)

  // Signing in, the way a visitor does: the form, the stub's token, and the
  // screens behind it.
  await step('signing in', async () => {
    await page.getByLabel('Email').fill('walker@example.com')
    await page.getByLabel('Password').fill('a-password')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await page.waitForURL(`${base}/`)
    // Exactly, because the screen behind the form also links to the reports
    // under a longer name, and a partial match would find both.
    await page.getByRole('link', { name: 'Reports', exact: true }).waitFor()
    check('the app shell is shown', `${base}/`, page.url())
  })

  // The reports, which is where the charts are: recharts draws them, and
  // shadcn's wrapper around it used to emit a stylesheet of its own.
  await step('the reports screen', async () => {
    await page.goto(`${base}/reports`, { waitUntil: 'networkidle' })
    await page.locator('.recharts-surface').first().waitFor()
    check('the charts are drawn', true, (await page.locator('.recharts-surface').count()) > 0)
  })

  // A dialog, which is what Radix locks the scroll behind, and the stylesheet
  // that lock builds is the one the nonce was needed for in the first place.
  await step('a dialog', async () => {
    await page.goto(`${base}/accounts`, { waitUntil: 'networkidle' })
    await page.getByRole('button', { name: 'Add account' }).click()
    await page.getByRole('dialog').waitFor()
    check('the dialog is open', true, await page.getByRole('dialog').isVisible())
    // The lock is what a refused stylesheet would have left off the page, so
    // the walk asks whether it took: a body that still scrolls behind an open
    // dialog is the symptom someone would have reported from production.
    check(
      'the scroll behind it is locked',
      'hidden',
      await page.evaluate(() => getComputedStyle(document.body).overflow),
    )
  })

  // A toast, which sonner styles from a stylesheet it would otherwise inject.
  await step('a toast', async () => {
    await page.getByRole('dialog').getByLabel('Name').fill('Walked in')
    await page.getByRole('dialog').getByRole('button', { name: 'Add account' }).click()
    const toast = page.getByText('Account added')
    await toast.waitFor()
    check('the toast is shown', true, await toast.isVisible())
    // Unstyled is what a refused stylesheet leaves, and sonner's own puts the
    // toaster in a fixed position. A static one means the stylesheet is gone.
    check(
      'the toast is styled',
      'fixed',
      await page.evaluate(() => {
        const toaster = document.querySelector('[data-sonner-toaster]')
        return toaster ? getComputedStyle(toaster).position : 'no toaster'
      }),
    )
  })

  // A theme change, which next-themes makes by writing to the page, and which
  // the app reads the nonce for as well.
  await step('a theme change', async () => {
    await page.getByRole('button', { name: 'Change theme' }).click()
    await page.getByRole('menuitem', { name: 'Dark' }).click()
    await page.waitForFunction(() => document.documentElement.classList.contains('dark'))
    check(
      'the dark theme is applied',
      true,
      await page.evaluate(() => document.documentElement.classList.contains('dark')),
    )
  })

  // The last step's check is taken before the page has finished settling, and
  // a stylesheet built on the way out would be raised after it. Nothing else
  // would ever report that one.
  const late = await newViolations()
  check(
    'nothing was refused after the last step',
    'none',
    late.length === 0 ? 'none' : summarise(late.map(describe)),
  )
} finally {
  await context.close()
  await browser.close()
}

// Anything the page complained about. A refusal is logged here too, so this is
// a second net under the events above, and it catches the rest: a failed
// request, a component that threw.
check('the walk logged no error', 'none', errors.length === 0 ? 'none' : summarise(errors))

if (failures !== 0) {
  console.log(`${failures} check(s) failed`)
  process.exit(1)
}

console.log('the walk found nothing the policy refused')
