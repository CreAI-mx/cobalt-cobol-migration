/** Sandbox terminals — COBOL oracle vs migrated C# CLI (same fixture). */
import { useCallback, useMemo, useState } from 'react'
import {
  postParityDemo,
  type ParityComparison,
  type ParityDemoResponse,
  type ParityDemoSide,
  type ParityTerminalPane,
} from '../lib/api'
import {
  compareParityTranscripts,
  comparisonSimilarityPct,
  formatOutputPreview,
  parseParityTranscript,
} from '../lib/parityTranscript'

interface Props {
  runId: string
  disabled?: boolean
}

const IDLE: Record<'cobol' | 'csharp', ParityTerminalPane> = {
  cobol: {
    title: 'COBOL — GnuCOBOL oracle',
    command: '',
    stdout: '# idle — Run COBOL compiles account_lookup.cbl and pipes the fixture account',
    exit_code: 0,
    ok: true,
  },
  csharp: {
    title: 'C# — CLI oracle',
    command: '',
    stdout: '# idle — Run C# executes dotnet run on *Cli with the same accounts.dat + stdin',
    exit_code: 0,
    ok: true,
  },
}

function paneRan(pane: ParityTerminalPane): boolean {
  return Boolean(pane.command)
}

function TermSandbox({
  side,
  pane,
  running,
  disabled,
  onRun,
}: {
  side: 'cobol' | 'csharp'
  pane: ParityTerminalPane
  running: boolean
  disabled?: boolean
  onRun: () => void
}) {
  const hint =
    side === 'cobol'
      ? 'cobc -x -free account_lookup.cbl -o oracle && echo $ACCT | ./oracle'
      : 'dotnet run --project *Cli.csproj -- account-lookup'

  return (
    <article className={`term-pane term-pane-${side}`} aria-label={pane.title}>
      <div className="term-pane-head">
        <span className="term-pane-title">{pane.title}</span>
        <span className={`term-exit ${pane.command ? (pane.ok ? 'ok' : 'fail') : 'idle'}`}>
          {pane.command ? `exit ${pane.exit_code}` : 'idle'}
        </span>
      </div>
      <div className="term-prompt-line mono" aria-hidden>
        <span className="term-prompt-user">cobalt</span>
        <span className="term-prompt-at">@</span>
        <span className="term-prompt-host">{side}</span>
        <span className="term-prompt-path">:~$</span>
        <span className="term-prompt-cmd">{pane.command || hint}</span>
      </div>
      <pre className="term-body mono">{pane.stdout || '(no output yet)'}</pre>
      <div className="term-pane-foot">
        <button
          type="button"
          className="btn btn-sm"
          disabled={disabled || running}
          onClick={onRun}
        >
          {running ? 'Running…' : side === 'cobol' ? 'Run COBOL' : 'Run C# CLI'}
        </button>
      </div>
    </article>
  )
}

function ParityDiffPanel({
  comparison,
  cobolStdout,
  csharpStdout,
  cobTx,
  csTx,
}: {
  comparison: ParityComparison
  cobolStdout: string
  csharpStdout: string
  cobTx: ReturnType<typeof parseParityTranscript>
  csTx: ReturnType<typeof parseParityTranscript>
}) {
  const equal = comparison.output_equal
  const mismatches = comparison.diffs.filter((d) => !d.equal)
  const similarity = comparisonSimilarityPct(comparison)
  const cobPreview = formatOutputPreview(cobolStdout, cobTx)
  const csPreview = formatOutputPreview(csharpStdout, csTx)

  return (
    <div
      className={`parity-diff-panel ${equal ? 'parity-diff-equal' : 'parity-diff-mismatch'}`}
      role="region"
      aria-label="COBOL vs C# output comparison"
    >
      <div className="parity-compare-visual">
        <div className="parity-compare-col parity-compare-col-cobol">
          <span className="parity-compare-col-label">Legacy COBOL output</span>
          <pre className="parity-compare-output mono">{cobPreview}</pre>
        </div>
        <div className="parity-compare-col parity-compare-col-csharp">
          <span className="parity-compare-col-label">Migrated C# output</span>
          <pre className="parity-compare-output mono">{csPreview}</pre>
        </div>
        <div className="parity-similarity-card" aria-label={`Similarity ${similarity} percent`}>
          <span className="parity-similarity-pct">{similarity}%</span>
          <span className="parity-similarity-caption">field match</span>
          <div className="parity-similarity-bar" role="presentation">
            <span className="parity-similarity-fill" style={{ width: `${similarity}%` }} />
          </div>
          <strong className={`parity-similarity-verdict ${equal ? 'ok' : 'fail'}`}>
            {equal ? 'MATCH' : 'MISMATCH'}
          </strong>
        </div>
      </div>

      {!comparison.display_equal && equal && (
        <p className="parity-output-banner-sub muted">
          Same business result; BALANCE display text may still differ on the console.
        </p>
      )}

      {!equal && mismatches.length > 0 && (
        <ul className="parity-fix-list">
          {mismatches.map((d) => (
            <li key={d.field}>
              <strong>{d.label}:</strong> {d.fix_hint ?? 'See terminal transcripts above.'}
            </li>
          ))}
        </ul>
      )}

      <table className="parity-compare-table mono">
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">COBOL</th>
            <th scope="col">C#</th>
            <th scope="col">Match</th>
          </tr>
        </thead>
        <tbody>
          {comparison.diffs.map((row) => (
            <tr key={row.field} className={row.equal ? '' : 'parity-row-mismatch'}>
              <th scope="row">{row.label}</th>
              <td>{row.cobol}</td>
              <td>{row.csharp}</td>
              <td className={row.equal ? 'parity-cell-ok' : 'parity-cell-fail'}>
                {row.equal ? 'Yes' : 'No'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function ParityConsole({ runId, disabled }: Props) {
  const [loadingSide, setLoadingSide] = useState<ParityDemoSide | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cobol, setCobol] = useState<ParityTerminalPane>(IDLE.cobol)
  const [csharp, setCsharp] = useState<ParityTerminalPane>(IDLE.csharp)
  const [verdict, setVerdict] = useState<ParityDemoResponse['verdict'] | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const [fixture, setFixture] = useState<string | null>(null)
  const [engine, setEngine] = useState<string | null>(null)
  const [statusHint, setStatusHint] = useState<string | null>(null)
  const [comparisonFromApi, setComparisonFromApi] = useState<ParityComparison | null>(null)

  const cobTx = useMemo(() => parseParityTranscript(cobol.stdout), [cobol.stdout])
  const csTx = useMemo(() => parseParityTranscript(csharp.stdout), [csharp.stdout])
  const showCompare = paneRan(cobol) && paneRan(csharp) && (cobTx.outcome || csTx.outcome)

  const comparison = useMemo(() => {
    if (comparisonFromApi) return comparisonFromApi
    if (showCompare) return compareParityTranscripts(cobTx, csTx)
    return null
  }, [comparisonFromApi, showCompare, cobTx, csTx])

  const apply = useCallback((res: ParityDemoResponse, side: ParityDemoSide) => {
    if (side === 'cobol') setCobol(res.cobol)
    else if (side === 'csharp') setCsharp(res.csharp)
    else {
      setCobol(res.cobol)
      setCsharp(res.csharp)
    }

    if (res.comparison) setComparisonFromApi(res.comparison)
    else if (side !== 'both') setComparisonFromApi(null)

    if (side === 'both') {
      setVerdict(res.verdict)
      setSummary(res.summary)
      setFixture(res.fixture)
      setEngine(res.parity_engine ?? null)
      setStatusHint(null)
    } else if (side === 'cobol') {
      setVerdict(null)
      setSummary(null)
      setStatusHint(
        res.cobol.ok
          ? 'COBOL finished — run C# or Compare both to check output parity.'
          : 'COBOL failed — fix compile/runtime before comparing.',
      )
    } else {
      setVerdict(null)
      setSummary(null)
      setStatusHint(
        res.csharp.ok
          ? 'C# finished — run COBOL or Compare both to compare.'
          : 'C# failed — check dotnet run output.',
      )
    }
  }, [])

  const run = (side: ParityDemoSide) => {
    setLoadingSide(side)
    setError(null)
    void postParityDemo(runId, side)
      .then((res) => apply(res, side))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoadingSide(null))
  }

  const busy = loadingSide !== null

  return (
    <section className="parity-console pane" aria-labelledby="parity-console-title">
      <header className="parity-console-head">
        <div className="parity-console-head-text">
          <h3 className="pane-title" id="parity-console-title">
            Parity sandbox
          </h3>
          <p className="pane-sub">
            Compare COBOL vs <code>*Cli</code> — same <code>accounts.dat</code> y stdin. Terminals above; <strong>comparison summary below</strong> shows each output and match score.
          </p>
        </div>
        <div className="parity-console-head-meta">
          {fixture && <span className="parity-meta-chip">{fixture}</span>}
          {engine && <span className="parity-meta-chip parity-meta-engine">{engine}</span>}
          <button
            type="button"
            className="btn primary parity-compare-btn"
            disabled={disabled || busy}
            onClick={() => run('both')}
          >
            {loadingSide === 'both' ? 'Comparing…' : 'Compare both'}
          </button>
        </div>
      </header>

      {error && (
        <p className="error-banner mono" role="alert">
          {error}
        </p>
      )}

      {verdict && summary && (
        <p className={`parity-verdict parity-verdict-${verdict}`} role="status">
          <strong>{verdict.toUpperCase()}</strong>
          {fixture ? ` · ${fixture}` : ''} — {summary}
        </p>
      )}

      {!verdict && statusHint && (
        <p className="parity-status-hint" role="status">
          {statusHint}
        </p>
      )}

      <div className="parity-term-grid">
        <TermSandbox
          side="cobol"
          pane={cobol}
          running={loadingSide === 'cobol' || loadingSide === 'both'}
          disabled={disabled}
          onRun={() => run('cobol')}
        />
        <TermSandbox
          side="csharp"
          pane={csharp}
          running={loadingSide === 'csharp' || loadingSide === 'both'}
          disabled={disabled}
          onRun={() => run('csharp')}
        />
      </div>

      {comparison && (
        <ParityDiffPanel
          comparison={comparison}
          cobolStdout={cobol.stdout}
          csharpStdout={csharp.stdout}
          cobTx={cobTx}
          csTx={csTx}
        />
      )}

      <footer className="parity-console-foot">
        <p className="muted parity-foot-hint">
          Use <strong>Compare both</strong> for verdict + table. Fix in <code>*Cli/Program.cs</code>,
          handlers or <code>accounts.dat</code>.
        </p>
      </footer>
    </section>
  )
}
