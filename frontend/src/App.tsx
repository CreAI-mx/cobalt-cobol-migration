/** Wizard shell — 5 steps, linear-gated forward / free backward. */
import { useEffect, useLayoutEffect, useState } from 'react'
import { RunProvider, useMigrationEvents, type RunState } from './hooks/useMigrationEvents'
import Step1Onboarding from './steps/Step1Onboarding'
import Step2Exploration from './steps/Step2Exploration'
import Step3Architecture from './steps/Step3Architecture'
import ApprovalGate from './components/ApprovalGate'
import PipelineProgress from './components/PipelineProgress'
import Step5Migrate from './steps/Step5Migrate'
import { readWizardSession, writeWizardSession } from './lib/wizardSession'
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  BrandMark,
  CheckIcon,
  ShieldIcon,
} from './components/Icons'

const STEPS = [
  {
    title: 'Onboarding',
    heading: 'Bring in the COBOL estate',
    lede: 'Upload a complete banking repository. Cobalt inventories every program before a single line is converted.',
  },
  {
    title: 'Exploration',
    heading: 'Map modules and agree on the COBOL estate',
    lede: 'Run the exploration engine: structure, CALL graph, migration modules, and notes — then lock the pack to feed migration.',
  },
  {
    title: 'Architecture',
    heading: 'Co-author the C# estate',
    lede: 'Pick a shape, write a re-architecture directive, recreate the After tree, then accept — conversion waits on you.',
  },
  {
    title: 'Corrections',
    heading: 'Human approval gate',
    lede: 'Go / no-go before conversion. Isolated agents do not start until you approve.',
  },
  {
    title: 'Migrate & Test',
    heading: 'Run, watch, verify',
    lede: 'Work items from the manifesto. Isolated agents, then build and tests. Download when it is real.',
  },
]

type ChipState = 'pending' | 'done' | 'warn' | 'live' | 'none'

function stepChip(step: number, run: RunState, visited: Set<number>): ChipState {
  const intakeDone = run.intake !== null
  switch (step) {
    case 0:
      return intakeDone ? 'done' : 'none'
    case 1:
      if (!intakeDone) return 'pending'
      return visited.has(step) || run.phaseMap.get('Phase 1')?.status === 'OK' ? 'done' : 'none'
    case 2:
      if (!intakeDone) return 'pending'
      if (run.architecture.action === 'accepted') return 'done'
      if (run.architecture.action === 'recreated') return 'warn'
      return visited.has(step) ? 'done' : 'none'
    case 3:
      if (!intakeDone) return 'pending'
      if (run.proposal.decision === 'approved') return 'done'
      if (run.proposal.decision === 'changes_requested') return 'warn'
      return 'none'
    case 4:
      if (run.live) return 'live'
      if (run.runStatus === 'PASSED') return 'done'
      if (run.runStatus) return 'warn'
      return run.proposal.decision === 'approved' ? 'none' : 'pending'
    default:
      return 'pending'
  }
}

function canEnter(step: number, run: RunState): boolean {
  const intakeDone = run.intake !== null
  if (step === 0) return true
  if (step === 4) return intakeDone && run.proposal.decision === 'approved'
  return intakeDone
}

function lockReason(step: number, run: RunState): string {
  if (step >= 1 && run.intake === null) return 'Add a .zip or GitHub URL and start intake first'
  if (step === 4 && run.proposal.decision !== 'approved')
    return 'Approve the architecture proposal in Corrections first'
  return ''
}

function Chip({ state }: { state: ChipState }) {
  switch (state) {
    case 'live':
      return (
        <span className="chip live">
          <span className="live-dot" /> LIVE
        </span>
      )
    case 'done':
      return (
        <span className="chip done">
          <CheckIcon width={10} height={10} /> DONE
        </span>
      )
    case 'warn':
      return (
        <span className="chip warn" title="Finished with blocked or skipped phases">
          <CheckIcon width={10} height={10} /> <span className="warn-dot" />
        </span>
      )
    case 'none':
      return null
    default:
      return <span className="chip pending">LOCKED</span>
  }
}

function useAppShellClass(live: boolean) {
  useLayoutEffect(() => {
    const shell = document.getElementById('app')
    if (shell) shell.className = `app${live ? ' is-live' : ''}`
  }, [live])
}

function Wizard() {
  const run = useMigrationEvents()
  useAppShellClass(run.live)
  const [current, setCurrent] = useState(0)
  const [visited, setVisited] = useState<Set<number>>(new Set([0]))
  const [sessionApplied, setSessionApplied] = useState(false)

  useEffect(() => {
    if (!run.hydrated) return
    if (!sessionApplied) {
      const saved = readWizardSession()
      if (saved && run.runId && saved.runId === run.runId) {
        let step = Math.min(saved.step, STEPS.length - 1)
        if (!canEnter(step, run)) {
          for (let s = step; s >= 0; s--) {
            if (canEnter(s, run)) {
              step = s
              break
            }
          }
        }
        const nextVisited =
          saved.visited.length > 0 ? saved.visited : [0, 1, 2, 3, 4].filter((n) => n <= step)
        setCurrent(step)
        setVisited(new Set(nextVisited))
      }
      setSessionApplied(true)
      return
    }
    if (!run.runId || current === 0) return
    writeWizardSession({ runId: run.runId, step: current, visited: [...visited] })
  }, [run.hydrated, run.runId, run.intake, run.proposal.decision, current, visited, sessionApplied])

  const goHome = () => {
    run.goHome()
    setCurrent(0)
    setVisited(new Set([0]))
  }

  const goTo = (step: number) => {
    if (step === 0) {
      goHome()
      return
    }
    if (!canEnter(step, run)) return
    setCurrent(step)
    setVisited((prev) => new Set(prev).add(step))
  }

  const totalCost = run.cost.reduce((s, c) => s + c.cost_usd, 0)
  const totalTok = run.cost.reduce((s, c) => s + c.input_tokens + c.output_tokens, 0)
  const step = STEPS[current]
  const nextLocked = current < STEPS.length - 1 && !canEnter(current + 1, run)

  if (!run.hydrated || !sessionApplied) {
    return (
      <RunProvider value={run}>
        <>
          <header className="app-header">
            <div className="brand-lockup">
              <span className="brand-mark">
                <BrandMark />
              </span>
              <div>
                <div className="brand">
                  Cobalt <span>//</span> COBOL → C#
                </div>
                <div className="brand-sub">Core banking migration console</div>
              </div>
            </div>
          </header>
          <main className="app-main" id="main">
            <p className="muted">Restoring last session…</p>
          </main>
        </>
      </RunProvider>
    )
  }

  return (
    <RunProvider value={run}>
      <>
        <a className="skip-link" href="#main">
          Skip to main content
        </a>
        <header className="app-header">
          <button
            type="button"
            className="brand-lockup"
            onClick={goHome}
            aria-label="Home — Onboarding"
          >
            <span className="brand-mark">
              <BrandMark />
            </span>
            <div>
              <div className="brand">
                Cobalt <span>//</span> COBOL → C#
              </div>
              <div className="brand-sub">Core banking migration console</div>
            </div>
          </button>
          <div className="header-spacer" />
          <div className="header-meta">
            <span className="trust-pill">
              <ShieldIcon width={13} height={13} />
              Human-gated
            </span>
            {run.runId && (
              <span className="mono muted run-pill" title="Current pipeline run">
                run {run.runId}
              </span>
            )}
            {run.runId && (
              <span className="cost-counter" title="Aggregate LLM spend this run">
                LLM spend <strong>${totalCost.toFixed(2)}</strong>
                <span className="cost-sep">·</span>
                {totalTok.toLocaleString()} tok
              </span>
            )}
          </div>
        </header>

        <main className="app-main" id="main">
          {current > 0 && (
          <nav className="stepper" aria-label="Migration steps">
            {STEPS.map((s, i) => {
              const chip = stepChip(i, run, visited)
              const enterable = canEnter(i, run)
              return (
                <div key={s.title} className="step-item">
                  {i > 0 && (
                    <span className={`step-rail ${enterable ? 'open' : ''}`} aria-hidden />
                  )}
                  <button
                    type="button"
                    className={`step-tab ${current === i ? 'current' : ''} ${chip === 'done' ? 'complete' : ''}`}
                    disabled={!enterable}
                    aria-current={current === i ? 'step' : undefined}
                    onClick={() => goTo(i)}
                  >
                    <span className="step-num">
                      {chip === 'done' || chip === 'warn' ? (
                        <CheckIcon width={12} height={12} />
                      ) : (
                        i + 1
                      )}
                    </span>
                    <span className="step-copy">
                      <span className="step-title">{s.title}</span>
                      <Chip state={chip} />
                    </span>
                  </button>
                </div>
              )
            })}
          </nav>
          )}

          <PipelineProgress
            phaseMap={run.phaseMap}
            live={run.live}
            fileStatus={run.fileStatus}
          />

          <div className="page-head">
            {current > 0 && (
              <p className="eyebrow">
                Step {current + 1} of {STEPS.length}
              </p>
            )}
            <h1>{step.heading}</h1>
            <p className="lede">{step.lede}</p>
          </div>

          {run.error && current !== 4 && (
            <div className="error-banner mono" role="alert">
              {run.error}
            </div>
          )}

          <div className="step-body">
            {current === 0 && (
              <Step1Onboarding
                key={run.runId ?? 'home'}
                onIntakeDone={() => {
                  setCurrent(1)
                  setVisited((prev) => new Set(prev).add(1))
                }}
                onOpenRun={() => {
                  // Bypass canEnter's gate check here — it reads a stale
                  // `run.proposal.decision` closure (loadHistoricalRun just
                  // set it async, before this render). We just hydrated the
                  // run ourselves; entering Step 5 is known-valid.
                  setCurrent(4)
                  setVisited((prev) => new Set(prev).add(4))
                }}
              />
            )}
            {current === 1 && <Step2Exploration />}
            {current === 2 && <Step3Architecture />}
            {current === 3 && (
              <ApprovalGate
                onApproved={() => goTo(4)}
                onApplyChanges={() => goTo(2)}
              />
            )}
            {current === 4 && <Step5Migrate />}
          </div>

          {current > 0 && (
          <div className="step-nav">
            <button
              type="button"
              className="btn"
              disabled={current === 0}
              onClick={() => goTo(current - 1)}
            >
              <ArrowLeftIcon width={14} height={14} />
              Back
            </button>
            {current < STEPS.length - 1 && (
              <div className="step-nav-next">
                <button
                  type="button"
                  className="btn primary"
                  disabled={nextLocked}
                  onClick={() => goTo(current + 1)}
                >
                  Next: {STEPS[current + 1].title}
                  <ArrowRightIcon width={14} height={14} />
                </button>
                {nextLocked && (
                  <span className="muted mono lock-reason">{lockReason(current + 1, run)}</span>
                )}
              </div>
            )}
          </div>
          )}
        </main>
      </>
    </RunProvider>
  )
}

export default function App() {
  return <Wizard />
}
