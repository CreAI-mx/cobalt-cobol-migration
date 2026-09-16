/** Foreman stages. Work-item count comes from the manifesto, not this list. */

import type { PhaseEvent } from './api'
export interface PhaseMeta {
  id: string
  skill: string
  label: string
  agentic: boolean
  runningLabel?: string
  railTitle?: string
  scrollTargetId?: string
}

export const PHASES: PhaseMeta[] = [
  { id: 'Analyzing', skill: 'migration-planner', label: 'Plan', agentic: true, runningLabel: 'Planning work items…' },
  { id: 'Generating', skill: 'work-item-orchestrator', label: 'Convert', agentic: true, runningLabel: 'Agents writing C#…' },
  { id: 'Building', skill: 'dotnet-build', label: 'Build', agentic: false },
  { id: 'Repairing', skill: 'bugfix-loop', label: 'Repair', agentic: true, runningLabel: 'Fixing compile errors…' },
  { id: 'Testing', skill: 'dotnet-test', label: 'Test', agentic: false },
  {
    id: 'Parity Validation',
    skill: 'parity-validation',
    label: 'Compare',
    railTitle: 'Compare · Original vs migrated',
    scrollTargetId: 'parity-console-title',
    agentic: false,
    runningLabel: 'COBOL oracle vs C# migrado (mismo fixture)…',
  },
  { id: 'Documenting', skill: 'migration-docs', label: 'Docs', agentic: true, runningLabel: 'Writing README + MIGRATION…' },
]

export const PHASE_BY_ID: Map<string, PhaseMeta> = new Map(
  PHASES.map((p) => [p.id, p]),
)

export function isAgentic(phaseId: string): boolean {
  return PHASE_BY_ID.get(phaseId)?.agentic ?? true
}

const FOREMAN_ORDER = [
  'Analyzing',
  'Generating',
  'Building',
  'Repairing',
  'Testing',
  'Parity Validation',
  'Documenting',
] as const

function laterForemanStageSettled(
  id: string,
  phaseMap: Map<string, PhaseEvent>,
): boolean {
  const idx = FOREMAN_ORDER.indexOf(id as (typeof FOREMAN_ORDER)[number])
  if (idx < 0) return false
  for (let i = idx + 1; i < FOREMAN_ORDER.length; i++) {
    const st = phaseMap.get(FOREMAN_ORDER[i])?.status
    if (st === 'OK' || st === 'SKIPPED' || st === 'BLOCKED') return true
  }
  return false
}

/** Phase tick is done — includes optional stages never emitted (e.g. Repair skipped). */
export function isPhaseSettled(id: string, phaseMap: Map<string, PhaseEvent>): boolean {
  const status = phaseMap.get(id)?.status
  if (status === 'OK' || status === 'SKIPPED' || status === 'BLOCKED') return true
  // Stale RUNNING (e.g. Analyzing never got OK in DB but Convert already finished).
  if (status === 'RUNNING' && laterForemanStageSettled(id, phaseMap)) return true
  if (id === 'Repairing' && !phaseMap.has('Repairing')) {
    return phaseMap.get('Building')?.status === 'OK'
  }
  if (id === 'Analyzing') {
    return (
      phaseMap.get('Generating')?.status === 'OK' ||
      phaseMap.get('Building')?.status === 'OK' ||
      phaseMap.get('Testing')?.status === 'OK' ||
      phaseMap.get('Parity Validation')?.status === 'OK' ||
      phaseMap.get('Documenting')?.status === 'OK'
    )
  }
  return false
}

export function countSettledPhases(phaseMap: Map<string, PhaseEvent>): number {
  return PHASES.filter((p) => isPhaseSettled(p.id, phaseMap)).length
}
