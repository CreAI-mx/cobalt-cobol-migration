/** Step 5 — agent stack + live session feed + circumstance-aware rerun. */
import { useCallback, useEffect, useRef, useState } from 'react'
import { GearIcon, SparkIcon } from './Icons'
import ParityConsole from './ParityConsole'
import AgentSessionPanel from './AgentSessionPanel'
import { useRun } from '../hooks/useMigrationEvents'
import { PHASES } from '../lib/phases'
import { getAgentStack, putAgentStack, type AgentStackConfig } from '../lib/api'
import { STACK_TOOLS, type StackToolId } from '../lib/agentStack'

interface Props {
  runId: string
  disabled?: boolean
  allowAgentRerun?: boolean
}

type SaveState = 'idle' | 'saving' | 'saved' | 'error'

export default function AgentStackSurface({ runId, disabled, allowAgentRerun }: Props) {
  const { events, live, agentRerun, error: runError } = useRun()
  const [rerunBusy, setRerunBusy] = useState(false)
  const [circumstance, setCircumstance] = useState('')
  const [tools, setTools] = useState<Record<StackToolId, boolean>>({
    'parity-oracle': true,
    'openapi-driver': true,
    'agent-review': false,
  })
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const [loadError, setLoadError] = useState<string | null>(null)
  const debounceRef = useRef<number | null>(null)
  const skipNextSave = useRef(true)

  const applyConfig = useCallback((cfg: AgentStackConfig) => {
    setCircumstance(cfg.circumstance ?? '')
    setTools({
      'parity-oracle': cfg.tools?.['parity-oracle'] ?? true,
      'openapi-driver': cfg.tools?.['openapi-driver'] ?? true,
      'agent-review': cfg.tools?.['agent-review'] ?? false,
    })
  }, [])

  useEffect(() => {
    skipNextSave.current = true
    setLoadError(null)
    void getAgentStack(runId)
      .then((cfg) => {
        applyConfig(cfg)
        skipNextSave.current = false
        setSaveState('saved')
      })
      .catch((e: unknown) => {
        setLoadError(e instanceof Error ? e.message : String(e))
        skipNextSave.current = false
      })
  }, [runId, applyConfig])

  const persist = useCallback(
    (circ: string, toolMap: Record<StackToolId, boolean>) => {
      setSaveState('saving')
      void putAgentStack(runId, { run_id: runId, circumstance: circ, tools: toolMap })
        .then((cfg) => {
          applyConfig(cfg)
          setSaveState('saved')
        })
        .catch(() => setSaveState('error'))
    },
    [runId, applyConfig],
  )

  const scheduleSave = useCallback(
    (circ: string, toolMap: Record<StackToolId, boolean>) => {
      if (skipNextSave.current) return
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
      debounceRef.current = window.setTimeout(() => persist(circ, toolMap), 500)
    },
    [persist],
  )

  const onCircChange = (value: string) => {
    setCircumstance(value)
    scheduleSave(value, tools)
  }

  const toggleTool = (id: StackToolId) => {
    setTools((prev) => {
      const next = { ...prev, [id]: !prev[id] }
      scheduleSave(circumstance, next)
      return next
    })
  }

  const onAgentRerun = () => {
    setRerunBusy(true)
    void agentRerun().finally(() => setRerunBusy(false))
  }

  const parityOn = tools['parity-oracle']
  const saveLabel =
    saveState === 'saving'
      ? 'Guardando…'
      : saveState === 'saved'
        ? 'Sincronizado'
        : saveState === 'error'
          ? 'Error al guardar'
          : ''

  return (
    <section className="agent-stack pane" aria-labelledby="agent-stack-title">
      <header className="agent-stack-head">
        <div>
          <h3 className="pane-title" id="agent-stack-title">
            Agent stack
          </h3>
          <p className="pane-sub">
            Sesión agentica en vivo (SSE) + circumstance persistido + rerun que re-inyecta el brief en conversión.
          </p>
        </div>
        <div className="agent-stack-head-meta">
          {saveLabel && <span className="parity-meta-chip">{saveLabel}</span>}
          {allowAgentRerun && (
            <button
              type="button"
              className="btn primary"
              disabled={disabled || live || rerunBusy}
              onClick={onAgentRerun}
            >
              {rerunBusy || live ? 'Agentes corriendo…' : 'Re-ejecutar agentes'}
            </button>
          )}
          <a className="btn btn-sm" href="/docs" target="_blank" rel="noreferrer">
            OpenAPI
          </a>
        </div>
      </header>

      {(loadError || runError) && (
        <p className="error-banner mono" role="alert">
          {loadError || runError}
        </p>
      )}

      <AgentSessionPanel events={events} live={live} circumstance={circumstance} />

      <div className="agent-stack-grid">
        <div className="agent-stack-col">
          <h4 className="agent-stack-section-title">Pipeline mix</h4>
          <ul className="agent-stack-phase-list">
            {PHASES.map((p) => (
              <li key={p.id} className={`agent-stack-phase ${p.agentic ? 'agentic' : 'deterministic'}`}>
                <span className="agent-stack-phase-icon" aria-hidden>
                  {p.agentic ? <SparkIcon className="icon icon-agentic" /> : <GearIcon className="icon icon-det" />}
                </span>
                <span className="agent-stack-phase-label">{p.label}</span>
                <span className="agent-stack-phase-skill mono">{p.skill}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="agent-stack-col">
          <h4 className="agent-stack-section-title">Circumstance</h4>
          <textarea
            className="agent-circumstance-input mono"
            rows={4}
            value={circumstance}
            onChange={(e) => onCircChange(e.target.value)}
            placeholder="Brief circumstancial para agentes…"
            disabled={disabled}
          />
          <h4 className="agent-stack-section-title">Tool slots</h4>
          <ul className="agent-tool-list">
            {STACK_TOOLS.map((t) => (
              <li key={t.id} className={`agent-tool-row ${t.kind}`}>
                <label className="agent-tool-label">
                  <input type="checkbox" checked={tools[t.id]} onChange={() => toggleTool(t.id)} disabled={disabled} />
                  <span className="agent-tool-name">
                    {t.kind === 'agentic' ? <SparkIcon className="icon icon-agentic" /> : <GearIcon className="icon icon-det" />}
                    {t.label}
                  </span>
                </label>
                <p className="muted agent-tool-desc">{t.description}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {parityOn ? (
        <div className="agent-stack-slot">
          <ParityConsole runId={runId} disabled={disabled || live} />
        </div>
      ) : (
        <p className="muted agent-stack-slot-off">Parity oracles desactivados.</p>
      )}
    </section>
  )
}
