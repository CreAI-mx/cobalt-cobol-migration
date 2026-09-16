/** Sandbox terminals — COBOL oracle vs migrated C# CLI (same fixture). */
import { useCallback, useMemo, useState } from 'react'
import {
  postParityDemo,
  type ParityComparison,
  type ParityDemoResponse,
  type ParityDemoSide,
  type ParityTerminalPane,
} from '../lib/api'
import { compareParityTranscripts, parseParityTranscript } from '../lib/parityTranscript'

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

function ParityDiffPanel({ comparison }: { comparison: ParityComparison }) {
  const equal = comparison.output_equal
  const mismatches = comparison.diffs.filter((d) => !d.equal)

  return (
    <div
      className={`parity-diff-panel ${equal ? 'parity-diff-equal' : 'parity-diff-mismatch'}`}
      role="region"
      aria-label="Comparación de salida COBOL vs C#"
    >
      <div className="parity-output-banner">
        <span className="parity-output-banner-label">¿Output igual?</span>
        <strong className="parity-output-banner-verdict">
          {equal ? 'SÍ — paridad OK' : 'NO — hay diferencias'}
        </strong>
        {!comparison.display_equal && equal && (
          <span className="parity-output-banner-sub muted">
            (Mismo negocio; texto de BALANCE en consola aún distinto)
          </span>
        )}
      </div>

      {!equal && mismatches.length > 0 && (
        <ul className="parity-fix-list">
          {mismatches.map((d) => (
            <li key={d.field}>
              <strong>{d.label}:</strong>{' '}
              {d.fix_hint ?? 'Revisar el transcript en las terminales.'}
            </li>
          ))}
        </ul>
      )}

      <table className="parity-compare-table mono">
        <thead>
          <tr>
            <th scope="col">Campo</th>
            <th scope="col">COBOL</th>
            <th scope="col">C#</th>
            <th scope="col">¿Igual?</th>
          </tr>
        </thead>
        <tbody>
          {comparison.diffs.map((row) => (
            <tr key={row.field} className={row.equal ? '' : 'parity-row-mismatch'}>
              <th scope="row">{row.label}</th>
              <td>{row.cobol}</td>
              <td>{row.csharp}</td>
              <td className={row.equal ? 'parity-cell-ok' : 'parity-cell-fail'}>
                {row.equal ? '✓' : '✗'}
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
          ? 'COBOL listo — ejecuta C# o Compare both para ver si el output es igual.'
          : 'COBOL falló — corrige compile/runtime antes de comparar.',
      )
    } else {
      setVerdict(null)
      setSummary(null)
      setStatusHint(
        res.csharp.ok
          ? 'C# listo — ejecuta COBOL o Compare both para ver diferencias.'
          : 'C# falló — revisa dotnet run.',
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
            Compara salida COBOL vs <code>*Cli</code> — mismo <code>accounts.dat</code> y stdin. Arriba verás
            si el output es igual y <strong>qué corregir en código</strong>.
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
            {loadingSide === 'both' ? 'Comparando…' : 'Compare both'}
          </button>
        </div>
      </header>

      {error && (
        <p className="error-banner mono" role="alert">
          {error}
        </p>
      )}

      {comparison && <ParityDiffPanel comparison={comparison} />}

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

      <footer className="parity-console-foot">
        <p className="muted parity-foot-hint">
          Usa <strong>Compare both</strong> para veredicto + tabla. Arregla en <code>*Cli/Program.cs</code>,
          handlers o lectura de <code>accounts.dat</code>.
        </p>
      </footer>
    </section>
  )
}
