/** Mocked /migration payloads for wizard e2e.
 * Importers: e2e/wizard-refresh.spec.ts, e2e/wizard-gating.spec.ts.
 * Mirrors GET tree/detail/architecture/gate/history/cost. No backend schema change.
 * User: "crea otro test e2e" / refresh on last page went back to start. */
import { type Page } from '@playwright/test'

export const RUN_ID = '01E2EREFRESHTEST00000000001'

export const TREE = {
  name: 'estate',
  type: 'dir' as const,
  is_cobol: false,
  children: [
    { name: 'main.cob', type: 'file' as const, is_cobol: true, children: null },
    { name: 'data.cob', type: 'file' as const, is_cobol: true, children: null },
  ],
}

export const ARCHITECTURE = {
  run_id: RUN_ID,
  revision: 1,
  shape: 'clean',
  directive: '',
  action: 'accepted',
  created_at: '2026-09-15T18:49:18+00:00',
}

export const GATE_HISTORY = [
  {
    decision: 'approved',
    comment: '',
    created_at: '2026-09-15T18:46:52+00:00',
  },
]

export const DETAIL = {
  run_id: RUN_ID,
  status: 'FAILED',
  source_repo: 'tjsingh85/cobol-accounting-system.git',
  started_at: '2026-09-15T18:46:22+00:00',
  finished_at: '2026-09-15T18:55:54+00:00',
  live: false,
  events: [
    {
      type: 'phase',
      phase: 'Phase 0',
      skill: 'cobol-discovery',
      status: 'OK',
      detail: '2 files inventoried',
    },
    {
      type: 'phase',
      phase: 'Phase 4',
      skill: 'cobol-to-csharp-conversion',
      status: 'BLOCKED',
      detail: 'HITL accepted rev 1 shape=clean — conversion finished this run',
    },
  ],
}

export const SESSION = {
  runId: RUN_ID,
  step: 4,
  visited: [0, 1, 2, 3, 4],
}

export const SESSION_ARCHITECTURE = {
  runId: RUN_ID,
  step: 2,
  visited: [0, 1, 2],
}

export const SESSION_CORRECTIONS = {
  runId: RUN_ID,
  step: 3,
  visited: [0, 1, 2, 3],
}

export const GATE_REJECTED = [
  {
    decision: 'rejected' as const,
    comment: 'rename the doc as documentation-master.md',
    created_at: '2026-09-15T18:50:00+00:00',
  },
]

export async function stubRunApis(
  page: Page,
  opts: { gate?: typeof GATE_HISTORY } = {},
) {
  const gate = opts.gate ?? GATE_HISTORY
  await page.route(`**/migration/${RUN_ID}/tree`, async (route) => {
    await route.fulfill({ json: TREE })
  })
  await page.route(`**/migration/${RUN_ID}/detail`, async (route) => {
    await route.fulfill({ json: DETAIL })
  })
  await page.route(`**/migration/${RUN_ID}/architecture`, async (route) => {
    await route.fulfill({ json: ARCHITECTURE })
  })
  await page.route(`**/migration/${RUN_ID}/gate/history`, async (route) => {
    await route.fulfill({ json: gate })
  })
  await page.route(`**/migration/${RUN_ID}/cost`, async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route(`**/migration/${RUN_ID}/extracts`, async (route) => {
    await route.fulfill({ json: [] })
  })
  await page.route('**/migration/runs**', async (route) => {
    await route.fulfill({ json: [] })
  })
}

export async function seedWizard(page: Page, session: typeof SESSION) {
  await page.addInitScript(
    ({ key, value }) => {
      localStorage.setItem(key, JSON.stringify(value))
    },
    { key: 'cobalt.wizard.v1', value: session },
  )
}
