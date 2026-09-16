/** Final-deliverables contract for the migrated project. Sourced from
 * .claude/skills/migration-doc-generation/SKILL.md and design/05-unit-testing.md
 * — this renders the pipeline's own contract, it does not invent promises.
 * Whole-project scope per user requirement (2026-09-15).
 * Importer: Step3Architecture.tsx accordion. No API/schema change. User asked
 * for per-module/submodule docs, human README, and a Documentation Master so
 * agents jump to those MDs without reading everything. */

const DELIVERABLES: Array<{ title: string; detail: string; source: string }> = [
  {
    title: 'Documentation — ontological markdown graph',
    detail:
      'Root README.md is for humans. docs/ontology/GRAPH.md is the A-box (typed nodes + part_of / implements / depends_on / governs edges) — coding agents start there and open one node path. docs/ontology/SCHEMA.md is the T-box. Instance READMEs stay next to each module/use-case. Provenance MDs live under docs/ontology/provenance/. DOCUMENTATION.md is a derived reading map, not the ontology. English, dense, factual.',
    source: 'migration-doc-generation skill',
  },
  {
    title: 'Clean structure',
    detail:
      'Modular solution: one C# project per COBOL program, shared Contracts project for copybooks, one test project per source project, docs/ and assets/ carried over — nothing loose in the root.',
    source: 'design/01-architecture.md §2',
  },
  {
    title: 'Tests executed, not just written',
    detail:
      'Every migrated file ships with its xUnit test class generated in the same agent turn, COMPILED and RUN before acceptance: zero failing tests, zero skipped without a ticketed justification, coverage gates enforced (line >= 90% per class, branch >= 85%).',
    source: 'design/05-unit-testing.md §1, §3',
  },
  {
    title: 'Logs and traceability',
    detail:
      'Full per-file event log streamed live (this UI) and persisted per run under migration-state/, plus sha256 + LOC + provenance recorded for every input file at intake — each migrated artifact traces back to its source.',
    source: 'backend intake + pipeline event stream',
  },
  {
    title: 'Robustness evidence',
    detail:
      'Mandatory decimal/COMP-3 edge-case matrix per migrated numeric field (boundaries, truncation hazards, sign, scale overflow), structural presence check, sampled mutation testing (Stryker.NET), and Phase 6 parity validation running the migrated code against the original COBOL as a behavioral oracle.',
    source: 'design/05-unit-testing.md §5 + Phase 6',
  },
]

export default function DeliverablesContract() {
  return (
    <div className="card">
      <h2>Final deliverables contract</h2>
      <p className="muted">
        What a completed migration hands over — the whole project, not only the
        translated COBOL. Each item cites the design doc that mandates it; Phases
        4/5 are still stubbed this round, so none of this is claimed as done yet.
      </p>
      <ul className="deliverables-list">
        {DELIVERABLES.map((d) => (
          <li key={d.title}>
            <strong>{d.title}</strong>
            <p>{d.detail}</p>
            <span className="mono muted source-ref">{d.source}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
