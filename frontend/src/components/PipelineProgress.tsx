/** Background pipeline rail — 9 phase ticks + a moving bar so the wizard
 * stays usable while phases run off the current step. */
import { PHASES, countSettledPhases } from '../lib/phases'
import type { PhaseEvent } from '../lib/api'

interface Props {
  phaseMap: Map<string, PhaseEvent>
  live: boolean
  fileStatus: Map<string, string>
}

function isSettled(status: string | undefined): boolean {
  return status === 'OK' || status === 'SKIPPED' || status === 'BLOCKED'
}

export default function PipelineProgress({ phaseMap, live, fileStatus }: Props) {
  if (!live) return null

  const settled = countSettledPhases(phaseMap)
  const running = PHASES.find((p) => phaseMap.get(p.id)?.status === 'RUNNING')
  const left = PHASES.length - settled
  const pct = Math.round((settled / PHASES.length) * 100)
  const runningFiles = live
    ? [...fileStatus.values()].filter((s) => s.toUpperCase() === 'RUNNING').length
    : 0

  return (
    <div className="pipe-progress" aria-live="polite">
      <div className="pipe-progress-meta">
        <span className="mono">
          {live ? 'Running' : 'Pipeline'}
          {running ? ` · ${running.id} ${running.label}` : ''}
          {runningFiles > 0 ? ` · ${runningFiles} file${runningFiles === 1 ? '' : 's'} live` : ''}
        </span>
        <span className="mono">
          <strong>
            {settled}/{PHASES.length}
          </strong>{' '}
          done · {left} left · {pct}%
        </span>
      </div>
      <div
        className="progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Pipeline progress"
      >
        <div
          className={`progress-fill determinate ${running?.agentic ? 'agentic' : ''}`}
          style={{ width: `${Math.max(pct, live ? 6 : 0)}%` }}
        />
        {live && running ? <div className="progress-shimmer" /> : null}
      </div>
      <ol className="pipe-ticks">
        {PHASES.map((p) => {
          const status = phaseMap.get(p.id)?.status
          const cls = status === 'RUNNING'
            ? 'running'
            : status === 'BLOCKED'
              ? 'failed'
              : isSettled(status)
                ? 'ok'
                : ''
          return (
            <li
              key={p.id}
              className={`pipe-tick ${cls} ${p.agentic ? 'agentic' : ''}`}
              title={`${p.id} ${p.label}${status ? ` — ${status}` : ''}`}
            />
          )
        })}
      </ol>
    </div>
  )
}
