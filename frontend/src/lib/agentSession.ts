import type { MigrationEvent } from './api'
import { isAgentic } from './phases'

export interface AgentSessionLine {
  id: string
  phase: string
  status: string
  detail: string
  at: number
}

const SESSION_PHASES = new Set(['AgentSession'])

export function isAgentSessionPhase(phase: string): boolean {
  return SESSION_PHASES.has(phase) || isAgentic(phase)
}

/** Recent agent-visible activity from the shared SSE log. */
export function buildAgentSessionLines(events: MigrationEvent[], limit = 14): AgentSessionLine[] {
  const lines: AgentSessionLine[] = []
  events.forEach((e, idx) => {
    if (e.type === 'file') {
      if (!isAgentic(e.phase)) return
      lines.push({
        id: `f-${idx}-${e.file_path}`,
        phase: e.phase,
        status: e.status,
        detail: `${e.file_path} — ${e.detail}`.slice(0, 220),
        at: idx,
      })
      return
    }
    if (!isAgentSessionPhase(e.phase)) return
    lines.push({
      id: `p-${idx}-${e.phase}`,
      phase: e.phase,
      status: e.status,
      detail: e.detail.slice(0, 280),
      at: idx,
    })
  })
  return lines.slice(-limit)
}
