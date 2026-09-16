/** ActivityFeed — group-by-phase collapsible sections (design §Density 1).
 * Current phase auto-expands with streaming rows; completed phases collapse to
 * a one-line summary. Manual toggles override the automatic behavior.
 * GenAI visual language: agentic rows get the violet left-border + pulse while
 * RUNNING; deterministic rows are grey, static, no animation. */
import { useState } from 'react'
import type { CostLogEntry, MigrationEvent, PhaseStatus } from '../lib/api'
import { PHASE_BY_ID, isAgentic, type PhaseMeta } from '../lib/phases'
import {
  AlertIcon,
  CheckIcon,
  DashIcon,
  GearIcon,
  SparkIcon,
  SpinnerIcon,
} from './Icons'

interface Props {
  events: MigrationEvent[]
  /** Phase id currently streaming (last phase seen while live), or null. */
  currentPhase: string | null
  cost: CostLogEntry[]
  /** When false, RUNNING rows stay frozen — no spinner, no pulse. */
  live?: boolean
  /** Latest HITL architecture action — hides stale WAITING rows after Accept. */
  archAction?: string
}

function statusIcon(status: PhaseStatus | string, agentic: boolean, live: boolean) {
  const s = status.toUpperCase()
  if (s === 'OK') return <CheckIcon className="icon icon-ok" />
  if (s === 'BLOCKED') return <AlertIcon className="icon icon-blocked" />
  if (s === 'RUNNING' && live)
    return <SpinnerIcon className={`icon ${agentic ? 'icon-agentic' : 'icon-det'}`} />
  if (s === 'RUNNING')
    return agentic ? <SparkIcon className="icon icon-agentic" /> : <GearIcon className="icon icon-det" />
  return <DashIcon className="icon icon-skip" />
}

function formatTokens(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n)
}

export default function ActivityFeed({ events, currentPhase, cost, archAction, live = false }: Props) {
  /** Manual overrides: phase id -> forced open/closed. */
  const [overrides, setOverrides] = useState<Map<string, boolean>>(new Map())

  const byPhase = new Map<string, MigrationEvent[]>()
  for (const e of events) {
    const list = byPhase.get(e.phase) ?? []
    list.push(e)
    byPhase.set(e.phase, list)
  }

  const costByPhase = new Map<string, { usd: number; tok: number }>()
  for (const c of cost) {
    const agg = costByPhase.get(c.phase) ?? { usd: 0, tok: 0 }
    agg.usd += c.cost_usd
    agg.tok += c.input_tokens + c.output_tokens
    costByPhase.set(c.phase, agg)
  }

  const toggle = (phaseId: string, currentlyOpen: boolean) => {
    setOverrides((prev) => new Map(prev).set(phaseId, !currentlyOpen))
  }

  const groups: PhaseMeta[] = []
  const seen = new Set<string>()
  for (const e of events) {
    if (e.phase === '__done__' || seen.has(e.phase)) continue
    seen.add(e.phase)
    groups.push(
      PHASE_BY_ID.get(e.phase) ?? {
        id: e.phase,
        skill: e.type === 'phase' ? e.skill : '',
        label: e.phase.replace(/^Phase\s+/, ''),
        agentic: isAgentic(e.phase) || /2|4|5/.test(e.phase),
      },
    )
  }

  if (groups.length === 0) {
    return (
      <p className="muted">
        {events.length === 0
          ? 'No persisted activity for this run. Older runs often have a verdict and no event log.'
          : 'No pipeline events yet — the feed streams here once the run starts.'}
      </p>
    )
  }

  return (
    <div className="feed activity-feed">
      {groups.map((meta) => {
        const rows = byPhase.get(meta.id) ?? []
        const phaseEvent = [...rows].reverse().find((e) => {
          if (e.type !== 'phase') return false
          if (archAction === 'accepted' && /^WAITING/i.test(e.detail)) return false
          return true
        })
        const summary = phaseEvent && phaseEvent.type === 'phase' ? phaseEvent.detail : ''
        const isWaiting = /^WAITING/i.test(summary) && archAction !== 'accepted'
        const rawStatus = phaseEvent && phaseEvent.type === 'phase'
          ? phaseEvent.status
          : live
            ? 'RUNNING'
            : 'SKIPPED'
        const status = !live && rawStatus === 'RUNNING' ? 'SKIPPED' : rawStatus
        const isCurrent = live && meta.id === currentPhase
        // Live: only the streaming phase expands — avoids every group open in a 240px pane.
        const autoOpen = live ? isCurrent : status === 'BLOCKED'
        const isOpen = overrides.get(meta.id) ?? autoOpen
        const phaseCost = costByPhase.get(meta.id)

        const summaryText = isWaiting ? 'WAITING — accept architecture on Step 3' : summary

        return (
          <section key={meta.id} className="feed-group">
            <button
              type="button"
              className="feed-group-header"
              onClick={() => toggle(meta.id, isOpen)}
              aria-expanded={isOpen}
            >
              <div className="feed-group-header-main">
                {statusIcon(status, meta.agentic, live)}
                <span className="label">
                  {meta.label}
                  <span className="feed-phase-id" aria-hidden="true">
                    {' · '}
                    {meta.id}
                  </span>
                </span>
                {meta.agentic && phaseCost && (
                  <span className="cost-chip">
                    ${phaseCost.usd.toFixed(2)} · {formatTokens(phaseCost.tok)} tok
                  </span>
                )}
              </div>
              {!isOpen && summaryText ? (
                <p className="feed-group-summary">{summaryText}</p>
              ) : null}
            </button>
            {isOpen && (
              <div className="feed-rows">
                {rows.map((e, idx) => {
                  const agentic = isAgentic(e.phase)
                  const key =
                    e.type === 'file'
                      ? `${meta.id}|f|${idx}|${e.file_path}|${e.status}|${e.detail}`
                      : `${meta.id}|p|${idx}|${e.status}|${e.detail}|${e.skill}`
                  if (e.type === 'phase') {
                    const prev = rows[idx - 1]
                    if (
                      prev &&
                      prev.type === 'phase' &&
                      prev.status === e.status &&
                      prev.detail === e.detail
                    ) {
                      return null
                    }
                  }
                  if (e.type === 'file') {
                    const rowRunning = live && e.status === 'RUNNING'
                    return (
                      <div key={key} className={`feed-row ${agentic ? 'agentic' : ''} ${rowRunning ? 'running' : ''}`}>
                        {statusIcon(e.status, agentic, live)}
                        <div className="feed-row-body">
                          <span className="label">{e.file_path}</span>
                          <span className="detail">{e.detail}</span>
                        </div>
                      </div>
                    )
                  }
                  const rowRunning = live && e.status === 'RUNNING'
                  const waitingRow = /^WAITING/i.test(e.detail)
                  if (waitingRow) {
                    const laterUnblocked = rows.slice(idx + 1).some(
                      (later) => later.type === 'phase' && !/^WAITING/i.test(later.detail),
                    )
                    if (archAction === 'accepted' || laterUnblocked) return null
                  }
                  const label =
                    waitingRow
                      ? 'Waiting for architecture accept…'
                      : rowRunning && meta.agentic && meta.runningLabel
                        ? meta.runningLabel
                        : e.skill
                  return (
                    <div key={key} className={`feed-row ${agentic ? 'agentic' : ''} ${rowRunning ? 'running' : ''}`}>
                      {rowRunning ? (
                        <SpinnerIcon className={`icon ${agentic ? 'icon-agentic' : 'icon-det'}`} />
                      ) : agentic ? (
                        <SparkIcon className="icon icon-agentic" />
                      ) : (
                        <GearIcon className="icon icon-det" />
                      )}
                      <div className="feed-row-body">
                        <span className="label">{label}</span>
                        <span className={`detail ${e.status === 'BLOCKED' ? 'icon-blocked' : ''}`}>
                          [{waitingRow ? 'WAITING' : e.status}] {e.detail}
                        </span>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        )
      })}
    </div>
  )
}
