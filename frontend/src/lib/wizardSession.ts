/** Last wizard page + run id. Survives refresh (localStorage).
 * Importers: App.tsx, useMigrationEvents.ts.
 * User: "por que si hago refresh en la ultima pagina me lleva hasta el inicio" */

export interface WizardSession {
  runId: string
  step: number
  visited: number[]
}

const KEY = 'cobalt.wizard.v1'

export function readWizardSession(): WizardSession | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<WizardSession>
    if (!parsed.runId || typeof parsed.step !== 'number') return null
    return {
      runId: parsed.runId,
      step: Math.min(4, Math.max(0, parsed.step)),
      visited: Array.isArray(parsed.visited) ? parsed.visited.filter((n) => n >= 0 && n <= 4) : [0],
    }
  } catch {
    return null
  }
}

export function writeWizardSession(session: WizardSession): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(session))
  } catch {
    /* quota / private mode — refresh will start at step 1 */
  }
}

export function clearWizardSession(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* ignore */
  }
}
