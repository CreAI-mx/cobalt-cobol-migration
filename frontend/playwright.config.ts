/** Playwright runner for Cobalt wizard e2e.
 * Importers: `npm run test:e2e` in frontend/. Hits the live app on :8123
 * (FastAPI StaticFiles + /migration). reuseExistingServer so a running
 * uvicorn is used; no --reload.
 * User: "crea otro test e2e" after refresh dumped step 5 back to onboarding. */
import { defineConfig, devices } from '@playwright/test'

const BASE = process.env.COBALT_E2E_BASE ?? 'http://127.0.0.1:8123'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: BASE,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
