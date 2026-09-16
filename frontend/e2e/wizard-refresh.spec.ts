/** E2E: refresh on Migrate & Test must not dump the user back to Onboarding.
 * Importer: Playwright `npm run test:e2e`. Stubs GET /migration/{id}/tree,
 * /detail, /architecture, /gate/history, /cost, /extracts, /runs.
 * User: "crea otro test e2e" after "por que si hago refresh en la ultima pagina
 * me lleva hasta el inicio". */
import { test, expect } from '@playwright/test'
import { SESSION, seedWizard, stubRunApis } from './fixtures/run'

test('refresh on Migrate restores the last wizard page', async ({ page }) => {
  await stubRunApis(page)
  await seedWizard(page, SESSION)

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Run, watch, verify' })).toBeVisible()
  await expect(page.getByText('After — C# backend')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Bring in the COBOL estate' })).toHaveCount(0)
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Migrate & Test/ }),
  ).toHaveAttribute('aria-current', 'step')
})

test('reload after restore still stays on Migrate', async ({ page }) => {
  await stubRunApis(page)
  await seedWizard(page, SESSION)

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Run, watch, verify' })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Run, watch, verify' })).toBeVisible()
  await expect(page.getByText('After — C# backend')).toBeVisible()
})
