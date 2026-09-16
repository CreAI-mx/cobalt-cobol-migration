/** Step 2 — Exploration: FileTree (left) + structural summary (right).
 * Everything shown here is deterministic output from Phases 0/1/3 — file
 * counts from intake, CALL-site totals and the CALL graph straight from the
 * phase event details (no synthesized numbers). Next is gated on intake only
 * (App.tsx): Phase 3 may still be waiting behind Phase 2 on older runs. */
import FileTree from '../components/FileTree'
import { GearIcon } from '../components/Icons'
import { useRun } from '../hooks/useMigrationEvents'

export default function Step2Exploration() {
  const { intake, phaseMap, fileStatus, live } = useRun()

  if (!intake) return null

  const p0 = phaseMap.get('Phase 0')
  const p1 = phaseMap.get('Phase 1')
  const p3 = phaseMap.get('Phase 3')
  const running = (ev: typeof p0) => Boolean(live && ev?.status === 'RUNNING')

  return (
    <div className="explore-layout">
      <div className="card">
        <h3>Repository tree</h3>
        <FileTree tree={intake.tree} fileStatus={fileStatus} storageKey="cobalt.tree.explore" inspect="source" />
      </div>

      <div className="card">
        <h3>Structural summary</h3>
        <div className="stat-row">
          <div className="stat">
            <div className="value">{intake.total_files}</div>
            <div className="label">Files</div>
          </div>
          <div className="stat">
            <div className="value">{intake.cobol_files}</div>
            <div className="label">COBOL programs</div>
          </div>
        </div>

        <div className={`phase-block ${running(p0) ? 'is-running' : ''}`}>
          <h3>
            <GearIcon width={12} height={12} /> Phase 0 · Discovery
          </h3>
          <p className="mono muted">{p0 ? p0.detail : 'Idle — no discovery event yet.'}</p>
          {running(p0) && <PhaseBar />}
        </div>

        <div className={`phase-block ${running(p1) ? 'is-running' : ''}`}>
          <h3>
            <GearIcon width={12} height={12} /> Phase 1 · Structural analysis
          </h3>
          <p className="mono muted">{p1 ? p1.detail : 'Idle — no analysis event yet.'}</p>
          {running(p1) && <PhaseBar />}
        </div>

        <div className={`phase-block ${running(p3) ? 'is-running' : ''}`}>
          <h3>
            <GearIcon width={12} height={12} /> Phase 3 · CALL graph
          </h3>
          {p3 ? (
            <p className="call-graph">{p3.detail}</p>
          ) : (
            <p className="mono muted">Idle — no CALL-graph event yet.</p>
          )}
          {running(p3) && <PhaseBar />}
        </div>
      </div>
    </div>
  )
}

function PhaseBar() {
  return (
    <div className="progress-track" aria-hidden>
      <div className="progress-fill" />
    </div>
  )
}
