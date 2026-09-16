/** Circumstantial work-item board. Renders the backend manifesto — N units,
 * not a fictitious 46-file tree.
 * Importers: steps/Step5Migrate.tsx. API: GET /migration/{id}/plan.
 * User: UI agéntica flexible circunstancial; menos es más.
 */
import type { MigrationPlan, WorkItem, WorkItemStatus } from '../lib/api'
import { SpinnerIcon } from './Icons'

const STATUS_LABEL: Record<WorkItemStatus, string> = {
  pending: 'To do',
  analyzing: 'Analyzing',
  generating: 'Generating',
  building: 'Building',
  testing: 'Testing',
  completed: 'Done',
  failed: 'Failed',
}

function sourcesOf(item: WorkItem): string {
  const n = item.source_paths.length
  if (!n) return item.kind
  return `${n} source file${n === 1 ? '' : 's'}`
}

export default function WorkItemBoard({
  plan,
  onMigrate,
  migrating,
}: {
  plan: MigrationPlan | null
  onMigrate: () => void
  migrating: boolean
}) {
  if (!plan) {
    return (
      <div className="card">
        <h2>No work-item manifesto</h2>
        <p className="muted">
          This run is from the previous 9-phase pipeline. There are no isolated
          work items to show. Activity below is the original log, if it was
          persisted. Start a new intake to migrate with the current orchestrator.
        </p>
      </div>
    )
  }
  const { progress, work_items: items, ui_blocks: blocks } = plan
  const agents = items.filter((w) =>
    ['analyzing', 'generating', 'building', 'testing'].includes(w.status),
  )
  const canDownload = blocks.some((b) => b.type === 'download')
  const showBuild = blocks.some((b) => b.type === 'build_gate')
  const showTest = blocks.some((b) => b.type === 'test_gate')
  const idle = plan.stage === 'pending' && !migrating

  return (
    <div className="work-board">
      <div className="work-board-head">
        <div>
          <p className="eyebrow">{plan.solution_name}</p>
          <h2>{plan.summary}</h2>
          <p className="muted">
            {progress.work_items_done} of {progress.work_items_total} units ·{' '}
            {progress.artifacts_integrated} of {progress.artifacts_expected} files
            on disk
          </p>
        </div>
        <div className="work-board-actions">
          {idle && (
            <button type="button" className="btn primary" onClick={onMigrate} disabled={migrating}>
              Migrar
            </button>
          )}
          {canDownload && (
            <a className="btn primary" href={`/migration/${encodeURIComponent(plan.run_id)}/artifact.zip`}>
              Descargar
            </a>
          )}
        </div>
      </div>

      <div
        className="work-meter"
        role="progressbar"
        aria-valuenow={progress.percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Migration progress"
      >
        <span style={{ width: `${progress.percent}%` }} />
        <em>{progress.percent}%</em>
      </div>

      {migrating && agents.length > 0 && (
        <ul className="agent-strip" aria-label="Active agents">
          {agents.map((a) => (
            <li key={a.work_item_id}>
              <SpinnerIcon width={12} height={12} />
              <strong>{a.agent_id ?? a.slug}</strong>
              <span>{STATUS_LABEL[a.status]} {a.title}</span>
            </li>
          ))}
        </ul>
      )}

      {(showBuild || showTest) && (
        <p className="gate-line">
          {showBuild && <span>Build {plan.stage === 'failed' ? 'failed' : plan.stage === 'building' ? 'running' : 'ok'}</span>}
          {showTest && <span> · Tests {plan.stage === 'testing' ? 'running' : plan.stage === 'completed' ? 'ok' : '—'}</span>}
        </p>
      )}

      <ol className="work-list">
        {items.map((item) => {
          const compact = item.status === 'completed'
          return (
            <li
              key={item.work_item_id}
              className={`work-card is-${item.status} ${compact ? 'compact' : ''}`}
            >
              <header>
                <span className="mono">{item.work_item_id}</span>
                <span className={`work-tag is-${item.status}`}>{STATUS_LABEL[item.status]}</span>
              </header>
              <h3>{item.title}</h3>
              {!compact && (
                <p className="muted">
                  {sourcesOf(item)} · {item.expected_paths.length} declared files
                </p>
              )}
              {item.error && <p className="error-inline">{item.error}</p>}
              {!compact && item.status !== 'pending' && (
                <ul className="work-files">
                  {item.expected_paths.map((p) => (
                    <li key={p} className="mono">{p}</li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
