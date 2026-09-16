import { useMemo } from 'react'
import { SparkIcon } from './Icons'
import type { MigrationEvent } from '../lib/api'
import { buildAgentSessionLines } from '../lib/agentSession'

interface Props {
  events: MigrationEvent[]
  live: boolean
  circumstance?: string
}

export default function AgentSessionPanel({ events, live, circumstance }: Props) {
  const lines = useMemo(() => buildAgentSessionLines(events), [events])
  const brief = (circumstance ?? '').trim()

  return (
    <div className={`agent-session-panel ${live ? 'is-live' : ''}`} role="region" aria-label="Agent session">
      <div className="agent-session-head">
        <span className="agent-session-title">
          <SparkIcon className="icon icon-agentic" /> Agent session
        </span>
        <span className={`agent-session-pulse ${live ? 'live' : 'idle'}`}>{live ? 'LIVE' : 'idle'}</span>
      </div>
      {brief ? (
        <p className="agent-session-brief mono" title={brief}>
          <strong>Brief:</strong> {brief.length > 160 ? `${brief.slice(0, 160)}…` : brief}
        </p>
      ) : (
        <p className="muted agent-session-brief">Sin circumstance — el rerun agentico no inyecta brief extra.</p>
      )}
      <ul className="agent-session-feed mono">
        {lines.length === 0 ? (
          <li className="agent-session-empty">Aún no hay eventos agenticos en el stream (Analyzing / Generating / Repair / Docs).</li>
        ) : (
          lines.map((ln) => (
            <li key={ln.id} className={`agent-session-row status-${ln.status.toLowerCase()}`}>
              <span className="agent-session-phase">{ln.phase}</span>
              <span className="agent-session-detail">{ln.detail}</span>
            </li>
          ))
        )}
      </ul>
    </div>
  )
}
