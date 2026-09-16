/** Step 5 progress meter — done vs remaining, not a lone RUNNING chip.
 * Importer: Step5Migrate.tsx. Reads EstateProgress + phaseMap. No API change.
 * User (verbatim): "solo dice ruinig pero enceito una animacion no es evidente
 * el progreso, no se sabe caunto va cuanto falta que peuden ir veindo" */
import { useState } from 'react'
import { artifactZipUrl, pushToGithub, type PhaseEvent, type RunStatus } from '../lib/api'
import type { EstateProgress } from '../lib/estateBuild'
import { PHASES, countSettledPhases } from '../lib/phases'
import { SpinnerIcon } from './Icons'
import RunTimer from './RunTimer'

interface Props {
  progress: EstateProgress
  phaseMap: Map<string, PhaseEvent>
  live: boolean
  waiting: boolean
  runStatus: RunStatus | null
  currentFiles: string[]
  error: string | null
  onRetry?: () => void
  retrying?: boolean
  startedAt?: string | null
  finishedAt?: string | null
  llmMs?: number
  /** Migration run id — shown in the meter headline whenever set. */
  executionId?: string | null
  /** When true, show the final C# zip download (partial runs included). */
  showArtifactDownload?: boolean
}

function leaf(path: string): string {
  return path.split('/').pop() ?? path
}

export default function RunProgress({
  progress,
  phaseMap,
  live,
  waiting,
  runStatus,
  currentFiles,
  error,
  onRetry,
  retrying,
  startedAt = null,
  finishedAt = null,
  llmMs = 0,
  executionId = null,
  showArtifactDownload = false,
}: Props) {
  const settled = countSettledPhases(phaseMap)
  const running = PHASES.find((p) => phaseMap.get(p.id)?.status === 'RUNNING')
  const phaseLeft = PHASES.length - settled
  const phaseIdx = running ? PHASES.findIndex((p) => p.id === running.id) + 1 : settled
  const { total, finished, remaining, pct, done, tested, inProgress, testing, bugfix } = progress

  const phaseHint = waiting
    ? 'Waiting for architecture accept'
    : running
      ? `${running.id} · ${running.runningLabel ?? running.label}`
      : live
        ? 'Pipeline streaming'
        : null

  const chip = waiting ? 'WAITING' : live ? 'RUNNING' : runStatus ?? 'IDLE'
  const chipClass = waiting || live ? 'running' : runStatus === 'PASSED' ? 'passed' : runStatus ? 'failed' : 'idle'

  return (
    <div className="run-meter" aria-live="polite">
      <div className="run-meter-top">
        <div className="run-meter-pct">
          {(live || waiting) && <SpinnerIcon className="run-meter-spin" width={28} height={28} />}
          <span className="run-meter-num">{pct}%</span>
        </div>
        <div className="run-meter-copy">
          <div className="run-meter-headline">
            <span className={`verdict ${chipClass}`}>
              {(live || waiting) && <SpinnerIcon width={12} height={12} />}
              {chip}
            </span>
            {executionId ? (
              <span className="run-meter-exec mono" title={executionId}>
                run {executionId}
              </span>
            ) : null}
            {!executionId && (
              <span className="run-meter-label">{phaseHint ?? 'Idle'}</span>
            )}
          </div>
          {executionId && phaseHint ? (
            <p className="run-meter-phase">{phaseHint}</p>
          ) : null}
          <p className="run-meter-counts mono">
            <strong>
              {finished} of {total}
            </strong>{' '}
            files done
            {inProgress > 0 ? ` · ${inProgress} in progress` : ''}
            {testing > 0 ? ` · ${testing} testing` : ''}
            {bugfix > 0 ? ` · ${bugfix} bugfix` : ''}
            {' · '}
            <strong>{remaining} remaining</strong>
            {' · '}
            {settled} of {PHASES.length} phases · {phaseLeft} left
            {!executionId && phaseHint ? ` · ${phaseHint}` : ''}
          </p>
          {currentFiles.length > 0 && (
            <p className="run-meter-now mono">
              Live {currentFiles.slice(0, 3).map(leaf).join(', ')}
              {currentFiles.length > 3 ? ` +${currentFiles.length - 3}` : ''}
            </p>
          )}
        </div>
        <RunTimer startedAt={startedAt} finishedAt={finishedAt} live={live} llmMs={llmMs} />
      </div>

      <div
        className="meter-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label={`${finished} of ${total} estate files done, ${remaining} remaining`}
      >
        {tested > 0 && <span className="meter-seg tested" style={{ flexGrow: tested }} />}
        {done > 0 && <span className="meter-seg done" style={{ flexGrow: done }} />}
        {bugfix > 0 && <span className="meter-seg failed" style={{ flexGrow: bugfix }} />}
        {inProgress > 0 && <span className="meter-seg live" style={{ flexGrow: Math.max(inProgress, 1) }} />}
        {testing > 0 && <span className="meter-seg testing" style={{ flexGrow: Math.max(testing, 1) }} />}
        {remaining > 0 && <span className="meter-seg rest" style={{ flexGrow: remaining }} />}
        {total === 0 && <span className="meter-seg rest" style={{ flexGrow: 1 }} />}
        {live && <span className="meter-shimmer" />}
      </div>

      <ul className="run-meter-stats">
        <li>
          <span className="n">{done}</span> done
        </li>
        <li>
          <span className="n">{tested}</span> tested
        </li>
        <li className={inProgress > 0 ? 'live' : ''}>
          <span className="n">{inProgress}</span> in progress
        </li>
        <li>
          <span className="n">{testing}</span> testing
        </li>
        <li>
          <span className="n">{bugfix}</span> bugfix
        </li>
        <li>
          <span className="n">{remaining}</span> to do
        </li>
        <li>
          <span className="n">
            {phaseIdx}/{PHASES.length}
          </span>{' '}
          phase
        </li>
      </ul>
      {error && (
        <p className="mono" style={{ color: 'var(--destructive)', margin: '8px 0 0' }}>
          {error}
        </p>
      )}
      {runStatus === 'FAILED' && !live && onRetry && (
        <div className="step-actions" style={{ marginTop: 10 }}>
          <button type="button" className="btn primary" disabled={retrying} onClick={onRetry}>
            {retrying ? 'Retrying…' : 'Retry run'}
          </button>
        </div>
      )}
      {showArtifactDownload && executionId && !live && (
        <div className="run-meter-deliverable">
          <a className="btn primary" href={artifactZipUrl(executionId)} download>
            Descargar proyecto C# (.zip)
          </a>
          <GithubPushButton runId={executionId} />
          <p className="muted run-meter-deliverable-hint">
            Entregable del run: código generado bajo <span className="mono">csharp/</span> (sin{' '}
            <span className="mono">bin/obj</span>).
            {runStatus === 'PASSED'
              ? ' Migración completada.'
              : runStatus === 'FAILED'
                ? ' Run fallido — incluye lo integrado hasta el corte.'
                : null}
          </p>
        </div>
      )}
    </div>
  )
}

/** Pushes csharp/ to a new public GitHub repo under the machine's already-
 * registered account (git credential helper, no token entry). User
 * (verbatim): "agrega el boton de generar repo de github un repo publico en
 * mi perfil". */
function GithubPushButton({ runId }: { runId: string }) {
  const [state, setState] = useState<'idle' | 'pushing' | 'done' | 'error'>('idle')
  const [repoUrl, setRepoUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (state === 'done' && repoUrl) {
    return (
      <a className="btn" href={repoUrl} target="_blank" rel="noreferrer">
        Ver repo en GitHub
      </a>
    )
  }

  return (
    <div>
      <button
        type="button"
        className="btn"
        disabled={state === 'pushing'}
        onClick={() => {
          setState('pushing')
          setError(null)
          pushToGithub(runId)
            .then((res) => {
              setRepoUrl(res.repo_url)
              setState('done')
            })
            .catch((err: Error) => {
              setError(err.message)
              setState('error')
            })
        }}
      >
        {state === 'pushing' ? 'Creando repo…' : 'Subir a GitHub (repo público)'}
      </button>
      {state === 'error' && error && (
        <p className="muted" style={{ color: 'var(--err, #e5484d)' }}>
          {error}
        </p>
      )}
    </div>
  )
}
