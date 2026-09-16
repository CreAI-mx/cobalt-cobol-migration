/** Step 2 — Visual exploration: CALL graph hero, rules collapsed, human pipeline. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import FilePeek from '../components/FilePeek'
import FileTree from '../components/FileTree'
import RepositoryLandscape from '../components/RepositoryLandscape'
import DocumentationArchitecture from '../components/DocumentationArchitecture'
import BusinessRuleCards from '../components/BusinessRuleCards'
import Accordion from '../components/Accordion'
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

function exploreRollup(map: Map<string, PhaseEvent>, live: boolean): { ok: boolean; running: boolean } {
  const events = EXPLORE_PHASES.map((n) => map.get(n))
  const running = live && events.some((e) => e?.status === 'RUNNING')
  const ok = EXPLORE_PHASES.every((n) => {
    const st = map.get(n)?.status
    return st === 'OK' || st === 'SKIPPED'
  })
  return { ok, running }
}

export default function Step2Exploration() {
  const { intake, phaseMap, fileStatus, live, runId, startExploration, error } = useRun()
  const [session, setSession] = useState<ExplorationSessionResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [peekPath, setPeekPath] = useState<string | null>(null)
  const [phaseDetail, setPhaseDetail] = useState(false)

  const pack = session?.locked_pack ?? session?.draft_pack ?? null
  const modules = pack?.modules ?? []

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    const load = () => {
      void getExplorationStatus(runId)
        .then((s) => {
          if (!cancelled) setSession(s)
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

  const essLive = Boolean(session?.live || live)
  const understand = exploreRollup(explorePhaseMap, essLive)
  const reviewOk = session?.status === 'LOCKED'
  const allRules = useMemo(() => {
    const byId = new Map<string, (typeof modules)[number]['business_rules'][number]>()
    for (const mod of modules) {
      for (const r of mod.business_rules ?? []) {
        const key = r.id || `${mod.entrypoint_path ?? ''}:${r.text}`
        if (!byId.has(key)) byId.set(key, r)
      }
    }
    return [...byId.values()]
  }, [modules])

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
          <span className="mono muted">Session: {session?.status ?? 'DRAFT'}</span>
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
            <header className="explore-pane-head">
              <h3>Pipeline</h3>
              <p className="muted">Human view · internals stay in the log</p>
            </header>
            <div className={`phase-strip${understand.running ? ' is-running' : ''}`}>
              <span className={`phase-strip-dot${understand.ok ? ' is-ok' : ''}${understand.running ? ' is-run' : ''}`} aria-hidden />
              <span className="phase-strip-label">Understanding your code</span>
            </div>
            <div className="phase-strip">
              <span className={`phase-strip-dot${reviewOk ? ' is-ok' : ''}`} aria-hidden />
              <span className="phase-strip-label">Review (lock)</span>
            </div>
            <button type="button" className="btn small phase-detail-toggle" onClick={() => setPhaseDetail((v) => !v)}>
              {phaseDetail ? 'Hide detail' : 'Show detail'}
            </button>
            {phaseDetail && EXPLORE_PHASES.map((name) => {
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
          <header className="explore-pane-head"><h3>Estate map</h3><p className="muted">Pseudocode flow · rombos, bucles, yes/no</p></header>
          {!pack ? (
            <p className="muted">Run exploration to build the visual map.</p>
          ) : (
            <>
              <RepositoryLandscape
                pack={pack}
                onSelectProgram={setPeekPath}
                graphLive={essLive && explorePhaseMap.get('Exploration · Graph')?.status === 'RUNNING'}
              />
              <Accordion title="Business rules" hint={`${allRules.length} rules`}>
                <BusinessRuleCards rules={allRules} onOpenAnchor={setPeekPath} />
              </Accordion>
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
