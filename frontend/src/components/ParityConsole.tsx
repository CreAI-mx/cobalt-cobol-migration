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
  compareParityOutputs,
  comparisonSimilarityPct,
} from '../lib/parityTranscript'

interface Props {
  runId: string
  disabled?: boolean
}

const IDLE: Record<'cobol' | 'csharp', ParityTerminalPane> = {
  cobol: {
    title: 'COBOL — GnuCOBOL oracle',
    command: '',
    stdout: '# idle — Run COBOL compiles the legacy program with the run fixture input',
    exit_code: 0,
    ok: true,
  },
  csharp: {
    title: 'C# — CLI oracle',
    command: '',
    stdout: '# idle — Run C# executes the migrated CLI with the same fixture input',
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
      ? 'cobc -x -free <program.cbl> -o oracle && …'
      : 'dotnet run --project <*Cli.csproj> [args per parity-manifest]'

  return (
    <article className={`term-pane term-pane-${side}`} aria-label={pane.title}>
      <div className="term-pane-head">
        <span className="term-pane-title">{pane.title}</span>
        <span className={`term-exit ${pane.command ? (pane.ok ? 'ok' : 'fail') : 'idle'}`}>
          {pane.command ? `exit ${pane.exit_code}` : 'idle'}
        </span>
      </div>
      <div className="term-prompt-line mono" aria-hidden>
        <div className="term-prompt-prefix">
          <span className="term-prompt-user">cobalt</span>
          <span className="term-prompt-at">@</span>
          <span className="term-prompt-host">{side}</span>
          <span className="term-prompt-path">:~$</span>
        </div>
        <div className="term-prompt-cmd">{pane.command || hint}</div>
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

function parityFieldLabel(label: string): string {
  if (label.startsWith('Resultado')) return 'Outcome (FOUND / NOT FOUND)'
  return label
}

function matchCellLabel(row: ParityComparison['diffs'][number]): string {
  if (!row.equal) return 'No'
  if (row.display_equal === false && row.numeric_equal !== false) return 'Display differs'
  return 'Yes'
}

function ParityCompareTable({ comparison }: { comparison: ParityComparison }) {
  const equal = comparison.output_equal
  const similarity = comparisonSimilarityPct(comparison)

  return (
    <div className="parity-compare-table-wrap">
      <table
        className="parity-compare-table mono"
        aria-label={`Field comparison, ${similarity} percent match, ${equal ? 'match' : 'mismatch'}`}
      >
        <thead>
          <tr>
            <th scope="col" className="parity-col-field">
              Field
            </th>
            <th scope="col" className="parity-col-legacy">
              Legacy · COBOL
            </th>
            <th scope="col" className="parity-col-migrated">
              Migrated · C#
            </th>
            <th scope="col" className="parity-col-match">
              <span className="parity-match-head">
                <span className="parity-match-head-title">Match</span>
                <span className="parity-match-head-pct">{similarity}%</span>
                <span className="parity-match-head-mode">
                  {comparison.mode === 'lines' ? 'lines' : 'fields'}
                </span>
                <span className={`parity-match-head-verdict ${equal ? 'ok' : 'fail'}`}>
                  {equal ? 'MATCH' : 'MISMATCH'}
                </span>
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          {comparison.diffs.map((row) => (
            <tr key={row.field} className={row.equal ? 'parity-row-match' : 'parity-row-mismatch'}>
              <th scope="row">{parityFieldLabel(row.label)}</th>
              <td className="parity-td-legacy">{row.cobol}</td>
              <td className="parity-td-migrated">{row.csharp}</td>
              <td className={row.equal ? 'parity-cell-ok' : 'parity-cell-fail'}>
                {matchCellLabel(row)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ParityDiffPanel({
  comparison,
}: {
  comparison: ParityComparison
}) {
  const equal = comparison.output_equal
  const mismatches = comparison.diffs.filter((d) => !d.equal)

  return (
    <div
      className={`parity-diff-panel ${equal ? 'parity-diff-equal' : 'parity-diff-mismatch'}`}
      role="region"
      aria-label="COBOL vs C# output comparison"
    >
      {comparison.mode === 'lines' && (
        <p className="parity-output-banner-sub muted">
          Line-by-line comparison (normalized stdout). For manifest-driven parity, see Phase 6 in the run log.
        </p>
      )}

      {comparison.mode === 'structured' && !comparison.display_equal && equal && (
        <p className="parity-output-banner-sub muted">
          Same business result; display formatting may still differ on the console.
        </p>
      )}

      {!equal && mismatches.length > 0 && (
        <ul className="parity-fix-list">
          {mismatches.map((d) => (
            <li key={d.field}>
              <strong>{parityFieldLabel(d.label)}:</strong>{' '}
              {d.fix_hint ?? 'See terminal transcripts above.'}
            </li>
          ))}
        </ul>
      )}

      <ParityCompareTable comparison={comparison} />
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

  const bothExecuted = paneRan(cobol) && paneRan(csharp)

  const comparison = useMemo(() => {
    if (comparisonFromApi) return comparisonFromApi
    if (bothExecuted) return compareParityOutputs(cobol.stdout, csharp.stdout)
    return null
  }, [comparisonFromApi, bothExecuted, cobol.stdout, csharp.stdout])

  const apply = useCallback((res: ParityDemoResponse, side: ParityDemoSide) => {
    if (side === 'cobol') setCobol(res.cobol)
    else if (side === 'csharp') setCsharp(res.csharp)
    else {
      setCobol(res.cobol)
      setCsharp(res.csharp)
    }

    if (res.comparison) setComparisonFromApi(res.comparison)
    else if (side === 'both') setComparisonFromApi(null)

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
            Compare legacy COBOL vs migrated <code>*Cli</code> on the same fixture input for this run. Field
            diff when output matches a known shape; otherwise line-by-line stdout.
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

      <div className="parity-dual-columns">
        <div className="parity-side parity-side-legacy">
          <TermSandbox
            side="cobol"
            pane={cobol}
            running={loadingSide === 'cobol' || loadingSide === 'both'}
            disabled={disabled}
            onRun={() => run('cobol')}
          />
        </div>
        <div className="parity-side parity-side-migrated">
          <TermSandbox
            side="csharp"
            pane={csharp}
            running={loadingSide === 'csharp' || loadingSide === 'both'}
            disabled={disabled}
            onRun={() => run('csharp')}
          />
        </div>
      </div>

      {comparison && (
        <div className="parity-compare-below-terminals">
          <ParityDiffPanel comparison={comparison} />
        </div>
      )}

      <footer className="parity-console-foot">
        <p className="muted parity-foot-hint">
          Use <strong>Compare both</strong> for verdict + table. Fix migrated handlers, CLI args (
          <code>parity-manifest.json</code>), or fixture I/O to match legacy behavior.
        </p>
      </footer>
    </section>
  )
}
