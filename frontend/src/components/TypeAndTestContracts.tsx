/** Type-mapping and test-architecture contracts shown in Step 3. Every rule
 * here is sourced from the design docs (01-architecture.md §3.1,
 * 05-unit-testing.md §1/§3/§5) — this component RENDERS the rulebook, it does
 * not invent rules. Design not yet implemented in the pipeline (Phases 4/5
 * stubbed); labeled as the contract the conversion must satisfy. */

const TYPE_RULES: Array<{ cobol: string; csharp: string; rule: string }> = [
  {
    cobol: 'PIC 9(n)V9(m)',
    csharp: 'decimal (scale=m)',
    rule: 'NEVER double/float — binary FP cannot represent exact decimal scale. CRITICAL severity if violated.',
  },
  {
    cobol: 'COMP-3 (packed)',
    csharp: 'decimal',
    rule: 'Identical semantics to unpacked: implicit decimal point, fixed scale.',
  },
  {
    cobol: 'PIC 9(n) — unsigned',
    csharp: 'decimal/int + validation',
    rule: 'CLR types are signed: negative values must be rejected by explicit validation, never assumed.',
  },
  {
    cobol: 'PIC S9(...)',
    csharp: 'signed counterpart',
    rule: 'Sign presence comes from the PIC clause, carried as field metadata.',
  },
  {
    cobol: 'PIC X(n)',
    csharp: 'string',
    rule: 'Fixed-length text; length domain enforced at boundaries.',
  },
  {
    cobol: 'MOVE / ACCEPT into V99',
    csharp: 'truncate, not round',
    rule: 'COBOL truncates extra decimals with no rounding — migrated parsing must reproduce truncation, not MidpointRounding.',
  },
]

const TEST_GATES: Array<{ gate: string; threshold: string }> = [
  { gate: 'Line coverage (migrated class)', threshold: '>= 90%' },
  { gate: 'Branch coverage (migrated class)', threshold: '>= 85%' },
  { gate: 'Line coverage (whole project, rolling)', threshold: '>= 80%' },
  { gate: 'Mutation score (Stryker.NET)', threshold: '>= 60% — informational in v1' },
]

const EDGE_MATRIX = [
  'Min domain value (0.00)',
  'Max domain value (e.g. 999999.99 for PIC 9(6)V99)',
  'Zero and boundary-adjacent values',
  'Rounding hazard: 100.005 must TRUNCATE per COBOL, not midpoint-round',
  'Negative input rejected (unsigned PIC 9 — CLR decimal is signed, validate explicitly)',
  'Scale overflow: 10.001 into scale=2 must truncate/reject, never silently retain hidden precision',
]

export default function TypeAndTestContracts() {
  return (
    <>
      <div className="card">
        <h2>Type mapping contract (tipados)</h2>
        <p className="muted">
          Deterministic lookup table + codegen — numeric semantics are never left
          to LLM arithmetic reasoning. Every migrated field carries its provenance
          as an annotation, e.g.{' '}
          <span className="mono">{'// COBOL: PIC 9(6)V99, unsigned, scale=2, COMP-3=false'}</span>,
          so test generation reads domain bounds without re-parsing the source.
          Source: design/01-architecture.md §3.1, design/05-unit-testing.md §5.
        </p>
        <div className="table-scroll">
          <table className="contract-table">
            <thead>
              <tr>
                <th>COBOL</th>
                <th>C# target</th>
                <th>Rule</th>
              </tr>
            </thead>
            <tbody>
              {TYPE_RULES.map((r) => (
                <tr key={r.cobol}>
                  <td className="mono">{r.cobol}</td>
                  <td className="mono">{r.csharp}</td>
                  <td>{r.rule}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Test architecture (pruebas)</h2>
        <p className="muted">
          xUnit + Moq + coverlet. The test class is generated in the SAME agent
          turn that emits the migrated <span className="mono">.cs</span> — no
          production file is ever accepted without its tests. Zero failing and
          zero unjustified skipped tests. Source: design/05-unit-testing.md.
        </p>
        <h3>Acceptance gates (gate, not aspiration)</h3>
        <div className="table-scroll">
          <table className="contract-table">
            <thead>
              <tr>
                <th>Gate</th>
                <th>Threshold</th>
              </tr>
            </thead>
            <tbody>
              {TEST_GATES.map((g) => (
                <tr key={g.gate}>
                  <td>{g.gate}</td>
                  <td className="mono">{g.threshold}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <h3>Mandatory decimal edge-case matrix (per field with PIC 9...V99 / COMP-3 provenance)</h3>
        <ul className="edge-list">
          {EDGE_MATRIX.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
        <p className="muted" style={{ marginBottom: 0 }}>
          Edge-case presence is checked STRUCTURALLY, not just by coverage % — this
          is what prevents "90% line coverage, wrong money" from reaching the
          accepted-file gate. Phase 6 (parity validation) then runs the migrated
          code against the original COBOL as a behavioral oracle.
        </p>
      </div>
    </>
  )
}
