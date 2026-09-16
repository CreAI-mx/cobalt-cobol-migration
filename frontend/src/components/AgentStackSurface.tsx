/** Step 5 — live agent session feed + parity sandbox + optional agent rerun. */
import { useState } from 'react'
import ParityConsole from './ParityConsole'
import AgentSessionPanel from './AgentSessionPanel'
import { useRun } from '../hooks/useMigrationEvents'

interface Props {
  runId: string
  disabled?: boolean
  allowAgentRerun?: boolean
}

export default function AgentStackSurface({ runId, disabled, allowAgentRerun }: Props) {
  const { events, live, agentRerun, error: runError } = useRun()
  const [rerunBusy, setRerunBusy] = useState(false)

  const onAgentRerun = () => {
    setRerunBusy(true)
    void agentRerun().finally(() => setRerunBusy(false))
  }

  return (
    <section className="agent-stack pane" aria-labelledby="agent-stack-title">
      <header className="agent-stack-head">
        <div>
          <h3 className="pane-title" id="agent-stack-title">
            Agent stack
          </h3>
          <p className="pane-sub">
            Live agent session from the run stream and parity sandbox below. Use{' '}
            <strong>Re-run agents</strong> to restart conversion with the same run id when the pipeline is idle.
          </p>
        </div>
        <div className="agent-stack-head-meta">
          {allowAgentRerun && (
            <button
              type="button"
              className="btn primary"
              disabled={disabled || live || rerunBusy}
              onClick={onAgentRerun}
            >
              {rerunBusy || live ? 'Agents running…' : 'Re-run agents'}
            </button>
          )}
        </div>
      </header>

      {runError && (
        <p className="error-banner mono" role="alert">
          {runError}
        </p>
      )}

      <AgentSessionPanel events={events} live={live} />

      <div className="agent-stack-slot">
        <ParityConsole runId={runId} disabled={disabled || live} />
      </div>
    </section>
  )
}
