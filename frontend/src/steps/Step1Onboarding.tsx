/** Step 1 — Onboarding: deterministic-vs-agentic explainer + zip dropzone
 * or GitHub URL. Wizard advances only on intake 200 (gating lives in App). */
import { useEffect, useRef, useState } from 'react'
import { useRun } from '../hooks/useMigrationEvents'
import { listRuns } from '../lib/api'
import type { RunHistoryEntry } from '../lib/api'
import { GearIcon, GitHubIcon, SparkIcon, SpinnerIcon, UploadIcon } from '../components/Icons'

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.round(hrs / 24)}d ago`
}

function RunHistory({ onOpenRun }: { onOpenRun: () => void }) {
  const { loadHistoricalRun, runId, live, runStatus, intake, startedAt } = useRun()
  const [runs, setRuns] = useState<RunHistoryEntry[] | null>(null)
  const [opening, setOpening] = useState<string | null>(null)
  const [openErr, setOpenErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      listRuns()
        .then((rows) => {
          if (!cancelled) setRuns(rows)
        })
        .catch(() => {
          if (!cancelled) setRuns([])
        })
    }
    load()
    const handle = window.setInterval(load, 2000)
    return () => {
      cancelled = true
      window.clearInterval(handle)
    }
  }, [])

  const rows: RunHistoryEntry[] = []
  const byId = new Map((runs ?? []).map((r) => [r.run_id, r]))
  if (runId && intake) {
    const existing = byId.get(runId)
    const flying = live || runStatus === 'RUNNING'
    byId.set(runId, {
      run_id: runId,
      started_at: existing?.started_at ?? startedAt ?? new Date().toISOString(),
      finished_at: flying ? null : (existing?.finished_at ?? null),
      status: flying ? 'RUNNING' : (existing?.status ?? runStatus ?? 'FAILED'),
      source_repo: existing?.source_repo ?? 'current session',
      target_lang: existing?.target_lang ?? 'csharp',
      total_files: existing?.total_files || intake.total_files,
      cobol_files: existing?.cobol_files || intake.cobol_files,
      live: flying || Boolean(existing?.live),
    })
  }
  for (const r of byId.values()) rows.push(r)
  rows.sort((a, b) => {
    const aLive = Boolean(a.live) || a.status === 'RUNNING' || (a.run_id === runId && live)
    const bLive = Boolean(b.live) || b.status === 'RUNNING' || (b.run_id === runId && live)
    if (aLive !== bLive) return aLive ? -1 : 1
    return 0
  })

  if (runs === null && rows.length === 0) return null
  if (rows.length === 0) return null

  const open = async (r: RunHistoryEntry) => {
    setOpening(r.run_id)
    setOpenErr(null)
    try {
      await loadHistoricalRun(r.run_id, r.total_files, r.cobol_files)
      onOpenRun()
    } catch (e) {
      setOpenErr(e instanceof Error ? e.message : String(e))
    } finally {
      setOpening(null)
    }
  }

  const inFlight = (r: RunHistoryEntry) =>
    Boolean(r.live) || r.status === 'RUNNING' || (r.run_id === runId && live)

  const liveCount = rows.filter(inFlight).length

  return (
    <div className="card run-history-card">
      <h2>Execution history</h2>
      <p className="muted">
        {rows.length} run{rows.length === 1 ? '' : 's'}
        {liveCount > 0 ? ` · ${liveCount} in progress` : ''} — real, persisted.
        Click a run to inspect or retry it.
      </p>
      {openErr && <p className="mono" style={{ color: 'var(--destructive)' }}>{openErr}</p>}
      <ul className="run-history-list">
        {rows.map((r) => {
          const flying = inFlight(r)
          const kind = flying ? 'running' : r.status.toLowerCase()
          const label = flying ? 'IN PROGRESS' : r.status
          return (
            <li key={r.run_id}>
              <button
                type="button"
                className={`run-history-row run-history-${kind}`}
                disabled={opening === r.run_id}
                onClick={() => void open(r)}
              >
                <span className={`run-history-status status-${kind}`}>
                  {flying || opening === r.run_id ? <SpinnerIcon width={10} height={10} /> : null}
                  {label}
                </span>
                <span className="mono run-history-repo" title={r.source_repo}>
                  {r.source_repo.includes('/')
                    ? r.source_repo.split('/').slice(-2).join('/')
                    : r.source_repo}
                </span>
                <span className="muted">{r.cobol_files} COBOL / {r.total_files} files</span>
                <span className="muted run-history-time">{relativeTime(r.started_at)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

interface Props {
  onIntakeDone: () => void
  onOpenRun: () => void
}

export default function Step1Onboarding({ onIntakeDone, onOpenRun }: Props) {
  const { intake, doIntake } = useRun()
  const [file, setFile] = useState<File | null>(null)
  const [repoUrl, setRepoUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragover, setDragover] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const pick = (f: File | undefined | null) => {
    if (!f) return
    setFile(f)
    setRepoUrl('')
    setError(null)
  }

  const canStart = (!!file || repoUrl.trim().length > 0) && !busy && !intake

  const startIntake = async () => {
    if (!canStart) return
    setBusy(true)
    setError(null)
    const url = repoUrl.trim()
    try {
      await doIntake(url ? { repoUrl: url } : { file: file! })
      onIntakeDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
    <div className="onboarding-grid">
      <div className="card">
        <h2>How a banking estate is migrated</h2>
        <p className="muted">
          Load the estate. A planner names real work items. Migrar converts them
          with isolated agents, then <code>dotnet build</code> and tests gate the result.
          Two documents at the end: README.md and MIGRATION.md.
        </p>
        <div className="legend-grid">
          <div className="legend-tile">
            <span className="explainer-icon">
              <GearIcon />
            </span>
            <div>
              <strong>Foreman</strong>
              <p className="muted" style={{ margin: '4px 0 0' }}>
                FastAPI + SQLite: manifesto, isolated workspaces, hash integrator,
                build and test gates. Verifiable.
              </p>
            </div>
          </div>
          <div className="legend-tile agentic">
            <span className="explainer-icon agentic">
              <SparkIcon />
            </span>
            <div>
              <strong>Engineer</strong>
              <p className="muted" style={{ margin: '4px 0 0' }}>
                Claude Code plans once, then converts each work item in its own
                folder. Concurrency follows the work, not a fixed swarm.
              </p>
            </div>
          </div>
        </div>
        <p className="muted" style={{ marginBottom: 0, marginTop: 14 }}>
          Violet means an agent did the work. Grey means machinery. Progress is
          units on the manifesto, never a placeholder tree.
        </p>
      </div>

      <div className="card">
        <h2>Upload COBOL source</h2>
        <p className="muted">Full project — zip upload or a GitHub repository URL.</p>
        <div
          className={`dropzone ${dragover ? 'dragover' : ''}`}
          role="button"
          aria-label="Upload COBOL repository zip file"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click()
          }}
          onDragOver={(e) => {
            e.preventDefault()
            setDragover(true)
          }}
          onDragLeave={() => setDragover(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragover(false)
            pick(e.dataTransfer.files?.[0])
          }}
        >
          <div className="dropzone-icon">
            <UploadIcon width={22} height={22} />
          </div>
          <p style={{ margin: '0' }}>
            Drop a <span className="mono">.zip</span> of the COBOL repository,
            or click to browse
          </p>
          {file && <div className="picked">{file.name}</div>}
          <input
            ref={inputRef}
            type="file"
            accept=".zip"
            hidden
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </div>

        <div className="or-split" role="separator">or</div>

        <label className="field-label" htmlFor="github-url">
          <GitHubIcon width={14} height={14} /> GitHub repository
        </label>
        <input
          id="github-url"
          className="repo-input"
          type="url"
          inputMode="url"
          autoComplete="url"
          spellCheck={false}
          placeholder="https://github.com/org/core-banking"
          aria-describedby="github-hint"
          value={repoUrl}
          disabled={!!intake}
          onChange={(e) => {
            setRepoUrl(e.target.value)
            if (e.target.value) setFile(null)
            setError(null)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void startIntake()
          }}
        />
        <p id="github-hint" className="field-hint">
          Public https://github.com/owner/repo — cloned shallow, default branch.
        </p>

        {error && (
          <p className="mono" role="alert" style={{ color: 'var(--destructive)' }}>
            {error}
          </p>
        )}
        <div className="step-actions">
          <button
            type="button"
            className="btn primary"
            disabled={!canStart}
            onClick={() => void startIntake()}
          >
            {busy && <SpinnerIcon width={14} height={14} />}
            {intake
              ? 'Intake complete'
              : busy
                ? repoUrl.trim()
                  ? 'Cloning repository…'
                  : 'Reading source…'
                : 'Start Intake'}
          </button>
          {intake && (
            <span className="mono muted">
              run {intake.run_id} · {intake.cobol_files} COBOL files
            </span>
          )}
        </div>
        {busy && (
          <div className="progress-track intake-progress" role="progressbar" aria-label="Reading source">
            <div className="progress-fill" />
          </div>
        )}
      </div>
    </div>

    <RunHistory onOpenRun={onOpenRun} />
    </>
  )
}
