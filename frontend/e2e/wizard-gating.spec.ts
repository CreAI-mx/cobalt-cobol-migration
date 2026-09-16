/** E2E: wizard session gating — cold start, Architecture restore, rejected
 * Corrections must not unlock Migrate (and a Migrate session falls back).
 * Importer: Playwright `npm run test:e2e`. Stubs the same GET /migration
 * surfaces as wizard-refresh.spec.ts.
 * User: "crea otro test e2e" after refresh-restore on the last page. */
import { test, expect } from '@playwright/test'
import {
  GATE_REJECTED,
  SESSION,
  SESSION_ARCHITECTURE,
  SESSION_CORRECTIONS,
  seedWizard,
  stubRunApis,
} from './fixtures/run'

test('cold start without a session stays on Onboarding', async ({ page }) => {
  await page.route('**/migration/runs**', async (route) => {
    await route.fulfill({ json: [] })
  })

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Bring in the COBOL estate' })).toBeVisible()
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Onboarding/ }),
  ).toHaveAttribute('aria-current', 'step')
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Migrate & Test/ }),
  ).toBeDisabled()
  await expect(page.getByRole('heading', { name: 'Run, watch, verify' })).toHaveCount(0)
})

test('restore Architecture lands on the HITL workshop, not Onboarding', async ({ page }) => {
  await stubRunApis(page)
  await seedWizard(page, SESSION_ARCHITECTURE)

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Co-author the C# estate' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Human in the loop' })).toBeVisible()
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Architecture/ }),
  ).toHaveAttribute('aria-current', 'step')
  await expect(page.getByRole('heading', { name: 'Bring in the COBOL estate' })).toHaveCount(0)
})

test('rejected Corrections keeps Migrate locked', async ({ page }) => {
  await stubRunApis(page, { gate: GATE_REJECTED })
  await seedWizard(page, SESSION_CORRECTIONS)

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Human approval gate' })).toBeVisible()
  await expect(page.getByText('CHANGES REQUESTED')).toBeVisible()
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Migrate & Test/ }),
  ).toBeDisabled()
  await expect(page.getByText('Approve the architecture proposal in Corrections first')).toBeVisible()
})

test('Migrate session with a rejected gate falls back to Corrections', async ({ page }) => {
  await stubRunApis(page, { gate: GATE_REJECTED })
  await seedWizard(page, SESSION)

  await page.goto('/')

  await expect(page.getByRole('heading', { name: 'Human approval gate' })).toBeVisible()
  await expect(page.getByText('CHANGES REQUESTED')).toBeVisible()
  await expect(
    page.locator('.stepper').getByRole('button', { name: /Corrections/ }),
  ).toHaveAttribute('aria-current', 'step')
  await expect(page.getByRole('heading', { name: 'Run, watch, verify' })).toHaveCount(0)
})
