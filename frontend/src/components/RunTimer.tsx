/** Elapsed run clock — wall time from GET /migration/{id}/detail started_at
 * / finished_at. Ticks while live; freezes when the run settles.
 * Importers: RunProgress.tsx, Step5Migrate.tsx (phase rail).
 * User: "NECEITO TAMBIEN UNA ESPECIE DE TIMER". */
import { useEffect, useRef, useState } from 'react'
import { ClockIcon } from './Icons'

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return '00:00'
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

function llmLabel(latencyMs: number): string | null {
  if (!Number.isFinite(latencyMs) || latencyMs <= 0) return null
  return `LLM ${formatDuration(latencyMs)}`
}

interface Props {
  startedAt: string | null
  finishedAt: string | null
  live: boolean
  llmMs?: number
  compact?: boolean
}

export default function RunTimer({ startedAt, finishedAt, live, llmMs = 0, compact = false }: Props) {
  const [now, setNow] = useState(() => Date.now())
  const frozeAt = useRef<number | null>(null)

  useEffect(() => {
    if (live) frozeAt.current = null
    else if (frozeAt.current == null) frozeAt.current = Date.now()
  }, [live])

  useEffect(() => {
    if (!startedAt || !live) return
    const id = window.setInterval(() => setNow(Date.now()), 250)
    return () => window.clearInterval(id)
  }, [startedAt, live])

  if (!startedAt) return null

  const start = Date.parse(startedAt)
  if (!Number.isFinite(start)) return null
  const end = finishedAt
    ? Date.parse(finishedAt)
    : live
      ? now
      : (frozeAt.current ?? now)
  const elapsed = (Number.isFinite(end) ? end : now) - start
  const llm = llmLabel(llmMs)

  return (
    <div
      className={`run-timer${live ? ' is-live' : ''}${compact ? ' is-compact' : ''}`}
      role="timer"
      aria-live="off"
      aria-label={`Elapsed ${formatDuration(elapsed)}`}
    >
      <ClockIcon width={compact ? 12 : 16} height={compact ? 12 : 16} />
      <span className="run-timer-time mono">{formatDuration(elapsed)}</span>
      <span className="run-timer-caption">{live ? 'elapsed' : 'duration'}</span>
      {llm ? <span className="run-timer-llm mono">{llm}</span> : null}
    </div>
  )
}
