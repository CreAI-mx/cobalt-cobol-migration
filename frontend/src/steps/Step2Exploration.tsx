/** Step 2 — Visual exploration: repo map + generated docs (no heavy graph panels). */
import { useCallback, useEffect, useMemo, useState } from 'react'
import FilePeek from '../components/FilePeek'
import FileTree from '../components/FileTree'
import EstateCompositionBar from '../components/EstateCompositionBar'
import RepositoryLandscape from '../components/RepositoryLandscape'
import DocumentationArchitecture from '../components/DocumentationArchitecture'
import { SpinnerIcon } from '../components/Icons'
import { useRun } from '../hooks/useMigrationEvents'
import {
  getExplorationStatus,
  postExplorationLock,
  type ExplorationSessionResponse,
  type PhaseEvent,
} from '../lib/api'

const EXPLORE_PHASES = [
  'Exploration · Discovery',
  'Exploration · Structural',
  'Exploration · Dependency',
  'Exploration · Modules',
  'Exploration · Business logic',
  'Exploration · Graph',
  'Exploration · Documentation',
] as const

export default function Step2Exploration() {
  const { intake, phaseMap, fileStatus, live, runId, startExploration, error } = useRun()
  const [session, setSession] = useState<ExplorationSessionResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [peekPath, setPeekPath] = useState<string | null>(null)

  const pack = session?.locked_pack ?? session?.draft_pack ?? null
  const modules = pack?.modules ?? []

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const load = () => {
      void getExplorationStatus(runId)
        .then((s) => {
          if (!cancelled) {
            setSession(s)
          }
        })
        .catch(() => {})
    }
    load()
    const t = window.setInterval(load, session?.live || live ? 1500 : 4000)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [runId, live, session?.live])

  const explorePhaseMap = useMemo(() => {
    const m = new Map<string, PhaseEvent>()
    for (const [k, v] of phaseMap) {
      if (k.startsWith('Exploration')) m.set(k, v)
    }
    return m
  }, [phaseMap])

  const structuralProgress = explorePhaseMap.get('Exploration · Structural')?.detail ?? ''
  const essLive = Boolean(session?.live || live)

  const onRun = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    setLocalError(null)
    try {
      await startExploration(runId)
      setSession(await getExplorationStatus(runId))
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [runId, startExploration])

  const onLock = useCallback(async () => {
    if (!runId) return
    setBusy(true)
    setLocalError(null)
    try {
      setSession(await postExplorationLock(runId))
    } catch (e) {
      setLocalError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }, [runId])

  if (!intake) return null

  return (
    <div className="explore-workspace">
      <div className="explore-command-bar card">
        <div className="explore-command-actions">
          <button type="button" className="btn primary" disabled={busy || session?.status === 'LOCKED'} onClick={() => void onRun()}>
            {busy && essLive ? <SpinnerIcon width={14} height={14} /> : null}
            Run exploration
          </button>
          <button type="button" className="btn" disabled={busy || !pack || session?.status === 'LOCKED'} onClick={() => void onLock()}>
            Lock &amp; feed migration
          </button>
        </div>
        <div className="explore-command-meta">
          {essLive && (
            <span className="chip live">
              <span className="live-dot" /> LIVE
            </span>
          )}
          <span className="mono muted">Session: {session?.status ?? 'DRAFT'}{structuralProgress ? ` · ${structuralProgress}` : ''}</span>
          {pack && (
            <span className="explore-command-stats mono muted">
              {pack.inventory_summary.programs} pg · {modules.length} mod · {(pack.documentation?.documents ?? []).filter((d) => d.endsWith('.md')).length} docs
            </span>
          )}
        </div>
      </div>

      {(localError || error) && <p className="explore-error" role="alert">{localError ?? error}</p>}

      <div className="explore-layout explore-layout-2">
        <div className="card explore-pane explore-pane--source">
          <header className="explore-pane-head"><h3>Source tree</h3><p className="muted">COBOL intake · click to peek</p></header>
          <FileTree tree={intake.tree} fileStatus={fileStatus} storageKey="cobalt.tree.explore" inspect="source" />
          <div className="explore-source-pipeline">
            <header className="explore-pane-head"><h3>Pipeline</h3><p className="muted">Exploration phases</p></header>
            {EXPLORE_PHASES.map((name) => {
              const ev = explorePhaseMap.get(name)
              const agentic = name.includes('Business logic') || name.includes('Modules') || name.includes('Graph')
              const running = essLive && ev?.status === 'RUNNING'
              const ok = ev?.status === 'OK'
              return (
                <div key={name} className={`phase-strip${agentic ? ' is-agentic' : ''}${running ? ' is-running' : ''}`}>
                  <span className={`phase-strip-dot${ok ? ' is-ok' : ''}${running ? ' is-run' : ''}`} aria-hidden />
                  <span className="phase-strip-label">{name.replace('Exploration · ', '')}</span>
                </div>
              )
            })}
          </div>
        </div>

        <div className="card explore-pane explore-center explore-center--visual">
          <header className="explore-pane-head"><h3>Estate map</h3><p className="muted">One pseudocode flowchart</p></header>
          {!pack ? (
            <p className="muted">Run exploration to build the visual map.</p>
          ) : (
            <>
              <EstateCompositionBar pack={pack} />
              <RepositoryLandscape
                pack={pack}
                onSelectProgram={setPeekPath}
                graphLive={essLive && explorePhaseMap.get('Exploration · Graph')?.status === 'RUNNING'}
              />
            </>
          )}
        </div>
      </div>
      {pack && (
        <DocumentationArchitecture
          pack={pack}
          docPhaseLive={essLive && explorePhaseMap.get('Exploration · Documentation')?.status === 'RUNNING'}
          layout="full"
        />
      )}
      {peekPath && <FilePeek path={peekPath} mode="source" onClose={() => setPeekPath(null)} />}
    </div>
  )
}

