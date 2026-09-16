/** Step 5 — left phase rail + After C# tree with To do / In progress / Done.
 * Importers: App.tsx. Layout: .migrate-layout (phases | estate / activity). */
import { useEffect, useMemo, useState } from 'react'
import ActivityFeed from '../components/ActivityFeed'
import AgentStackSurface from '../components/AgentStackSurface'
import FileTree from '../components/FileTree'
import PhaseTimeline from '../components/PhaseTimeline'
import RunProgress from '../components/RunProgress'
import { useRun } from '../hooks/useMigrationEvents'
import { artifactZipUrl, getExtracts } from '../lib/api'
import {
  BUILD_TAG_LABEL,
  countTags,
  deriveEstateStatus,
  estateProgress,
  inProgressPaths,
  latestBuildPath,
  phaseIsWaiting,
  planBuildTags,
  treeFromPaths,
  type BuildTag,
} from '../lib/estateBuild'
import { deriveMapping, deriveTargetArchitecture, TARGET_ARCHITECTURE } from '../lib/targetArchitecture'

const LEGEND: BuildTag[] = ['pending', 'in-progress', 'testing', 'done', 'tested', 'bugfix']

export default function Step5Migrate() {
  const {
    events,
    live,
    error,
    runId,
    retry,
    startedAt,
    finishedAt,
    cost,
    doStart,
    intake,
    architecture,
    phaseMap,
    runStatus,
    plan,
  } = useRun()
  const [retrying, setRetrying] = useState(false)
  const [nameByFrom, setNameByFrom] = useState<Record<string, string>>({})
  const shape = architecture.shape

  useEffect(() => {
    if (!runId) return
    void getExtracts(runId)
      .then((rows) => {
        const next: Record<string, string> = {}
        for (const r of rows) {
          if (r.path && r.suggested_component_name?.trim()) {
            next[r.path] = r.suggested_component_name.trim()
          }
        }
        setNameByFrom(next)
      })
      .catch(() => { /* extracts optional */ })
  }, [runId])

  // Work-item orchestrator runs carry a real plan (plan.work_items[].expected_paths)
  // — use it verbatim instead of guessing a Clean Architecture shape client-side.
  // The old prediction invents files the real pipeline never declares (per-folder
  // README.md, .csproj, .sln), which is why a genuinely PASSED run could show 33%
  // with dozens of rows stuck on "To do" forever. Real files only, real progress.
  const planExpectedPaths = useMemo(
    () => plan?.work_items.flatMap((w) => w.expected_paths) ?? [],
    [plan],
  )
  const usePlanTree = planExpectedPaths.length > 0
  const proposedTree = usePlanTree
    ? treeFromPaths(planExpectedPaths)
    : intake
      ? deriveTargetArchitecture(intake.tree, shape, architecture.directive, nameByFrom)
      : TARGET_ARCHITECTURE
  const mapping = intake ? deriveMapping(intake.tree, shape, nameByFrom).mappings : []
  const buildTags = useMemo(
    () =>
      usePlanTree
        ? planBuildTags(planExpectedPaths, events, {
            phaseMap,
            runStatus,
            workItems: plan?.work_items,
            planStage: plan?.stage,
            finishedAt,
            live,
          })
        : deriveEstateStatus(events, mapping, proposedTree, phaseMap),
    [usePlanTree, planExpectedPaths, events, mapping, proposedTree, phaseMap, runStatus, plan?.work_items, plan?.stage, finishedAt, live],
  )
  const progress = estateProgress(countTags(buildTags))
  const waiting = live && phaseIsWaiting(phaseMap, 'Phase 4', architecture.action)
  const currentFiles = live ? inProgressPaths(buildTags) : []
  const focusPath = live ? latestBuildPath(events, buildTags) : null
  const executionIdRaw = runId ?? intake?.run_id ?? architecture.run_id
  const executionId = executionIdRaw?.trim() ? executionIdRaw.trim() : null
  const showArtifactDownload = Boolean(executionId && !live && progress.finished > 0)

  let currentPhase: string | null = null
  if (live) {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === 'phase' && events[i].phase !== '__done__') {
        currentPhase = events[i].phase
        break
      }
    }
  }

  return (
    <div>
      <RunProgress
        progress={progress}
        phaseMap={phaseMap}
        live={live}
        waiting={waiting}
        runStatus={runStatus}
        currentFiles={currentFiles}
        error={error}
        onRetry={() => {
          setRetrying(true)
          void retry().finally(() => setRetrying(false))
        }}
        retrying={retrying}
        startedAt={startedAt}
        finishedAt={finishedAt}
        llmMs={cost.reduce((s, c) => s + (c.latency_ms ?? 0), 0)}
        executionId={executionId}
        showArtifactDownload={showArtifactDownload}
      />

      <div className="migrate-layout">
        <aside className="pane phase-rail">
          <h3 className="pane-title">Phases</h3>
          <PhaseTimeline phaseMap={phaseMap} archAction={architecture.action} live={live} />
        </aside>

        <section className="pane estate-pane">
          <div className="estate-head">
            <div>
              <h3 className="pane-title">After — C# backend</h3>
              <p className="pane-sub">To do → In progress → Done → Tested</p>
            </div>
            {runId && !live && (
              <button type="button" className="btn primary" onClick={() => void doStart(runId)}>
                Migrar
              </button>
            )}
          </div>
          <div className="build-legend" aria-label="Construction tags">
            {LEGEND.map((t) => (
              <span key={t} className={`tree-tag tree-tag-${t}`}>
                {BUILD_TAG_LABEL[t]}
              </span>
            ))}
          </div>
          <FileTree
            tree={proposedTree}
            buildTags={buildTags}
            focusPath={focusPath}
            storageKey={`cobalt.tree.after.${shape}`}
            defaultExpandAll
            inspect="proposal"
            mappings={mapping}
          />
        </section>

        <section className="pane activity-pane">
          <div className="activity-pane-head">
            <h3 className="pane-title">Activity</h3>
            {showArtifactDownload && executionId && (
              <a className="btn" href={artifactZipUrl(executionId)} download>
                Descargar .zip
              </a>
            )}
          </div>
          <ActivityFeed events={events} currentPhase={currentPhase} cost={cost} live={live} />
        </section>
      </div>

      {runId && !live && (
        <AgentStackSurface runId={runId} disabled={live} allowAgentRerun={Boolean(runId)} />
      )}
    </div>
  )
}
