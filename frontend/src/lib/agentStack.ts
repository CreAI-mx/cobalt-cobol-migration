/** UI model for the hybrid agentic + deterministic execution stack (Step 5). */

export type StackToolKind = 'deterministic' | 'agentic'

export type StackToolId = 'parity-oracle' | 'openapi-driver' | 'agent-review'

export interface StackToolDef {
  id: StackToolId
  label: string
  kind: StackToolKind
  description: string
  defaultOn: boolean
}

export const STACK_TOOLS: StackToolDef[] = [
  {
    id: 'parity-oracle',
    label: 'Parity oracles',
    kind: 'deterministic',
    description: 'COBOL GnuCOBOL + migrated C# CLI on the same accounts.dat fixture.',
    defaultOn: true,
  },
  {
    id: 'openapi-driver',
    label: 'API / agent driver',
    kind: 'agentic',
    description: 'Same pipeline via REST + SSE — stack is editable in your harness, not frozen in the UI.',
    defaultOn: true,
  },
  {
    id: 'agent-review',
    label: 'Agent review hook',
    kind: 'agentic',
    description: 'Placeholder for circumstantial LLM verdicts (skills, prompts, tools vary per run).',
    defaultOn: false,
  },
]

const CIRC_KEY = (runId: string) => `cobalt.agent.circumstance.${runId}`
const TOOLS_KEY = (runId: string) => `cobalt.agent.tools.${runId}`

export function loadCircumstance(runId: string): string {
  try {
    return localStorage.getItem(CIRC_KEY(runId)) ?? ''
  } catch {
    return ''
  }
}

export function saveCircumstance(runId: string, text: string): void {
  try {
    localStorage.setItem(CIRC_KEY(runId), text)
  } catch {
    /* private mode */
  }
}

export function loadToolPrefs(runId: string): Record<StackToolId, boolean> {
  const base = Object.fromEntries(
    STACK_TOOLS.map((t) => [t.id, t.defaultOn]),
  ) as Record<StackToolId, boolean>
  try {
    const raw = localStorage.getItem(TOOLS_KEY(runId))
    if (!raw) return base
    const parsed = JSON.parse(raw) as Partial<Record<StackToolId, boolean>>
    return { ...base, ...parsed }
  } catch {
    return base
  }
}

export function saveToolPrefs(runId: string, prefs: Record<StackToolId, boolean>): void {
  try {
    localStorage.setItem(TOOLS_KEY(runId), JSON.stringify(prefs))
  } catch {
    /* ignore */
  }
}
