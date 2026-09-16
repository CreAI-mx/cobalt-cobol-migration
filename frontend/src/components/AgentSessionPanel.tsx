import { useMemo, useState } from 'react'
import { SparkIcon } from './Icons'
import type { MigrationEvent } from '../lib/api'
import { buildAgentSessionLines } from '../lib/agentSession'

interface Props {
  events: MigrationEvent[]
  live: boolean
  circumstance?: string
}

const SESSION_PREVIEW_ROWS = 4

export default function AgentSessionPanel({ events, live, circumstance }: Props) {
  const [expanded, setExpanded] = useState(false)
  const lines = useMemo(() => buildAgentSessionLines(events), [events])
  const brief = (circumstance ?? '').trim()
  const needsToggle = lines.length > SESSION_PREVIEW_ROWS
  const visibleLines = expanded || !needsToggle ? lines : lines.slice(-SESSION_PREVIEW_ROWS)

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
        <p className="muted agent-session-brief">No circumstance — agent rerun will not inject an extra brief.</p>
      )}
      <ul className="agent-session-feed mono">
        {lines.length === 0 ? (
          <li className="agent-session-empty">Aún no hay eventos agenticos en el stream (Analyzing / Generating / Repair / Docs).</li>
        ) : (
          visibleLines.map((ln) => (
            <li key={ln.id} className={`agent-session-row status-${ln.status.toLowerCase()}`}>
              <span className="agent-session-phase">{ln.phase}</span>
              <span className="agent-session-detail">{ln.detail}</span>
            </li>
          ))
        )}
      </ul>
      {needsToggle && (
        <div className="agent-session-foot">
          <button
            type="button"
            className="agent-session-toggle"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded
              ? 'Collapse session'
              : `Show full session (${lines.length} events)`}
          </button>
          {!expanded && (
            <span className="muted agent-session-foot-hint">
              Showing last {SESSION_PREVIEW_ROWS} rows
            </span>
          )}
        </div>
      )}
    </div>
  )
}
