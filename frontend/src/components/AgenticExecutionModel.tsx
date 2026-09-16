/** Multi-agent execution model — HOW the agentic phases run once wired.
 * Everything under "Defined in the pipeline skills" is sourced from
 * .claude/skills/{cobol-business-logic-extraction, cobol-to-csharp-conversion,
 * csharp-test-generation, bugfix-loop}/SKILL.md. The "User quality contract"
 * block captures requirements added 2026-09-15 (SOLID, versioning, design
 * patterns, anti-spaghetti) that are PENDING adoption into the Phase 4 skill
 * prompt — shown as pending, never claimed as enforced. */
import { GearIcon, SparkIcon } from './Icons'

const AGENTS: Array<{ phase: string; name: string; how: string }> = [
  {
    phase: 'Phase 2',
    name: 'Business-logic extraction agent',
    how: 'LLM reads each parsed program and produces business rules, user stories and a glossary — the input that upgrades the architecture proposal from filename heuristics to behavior-derived naming.',
  },
  {
    phase: 'Phase 4',
    name: 'Conversion agents — one per file',
    how: 'Headless Claude Code per COBOL file, FRESH session each (no shared chat history; state flows through the run database), leaf-first over the dependency graph. Exit gate per file: dotnet build must pass before the file is handed to Phase 5.',
  },
  {
    phase: 'Phase 5',
    name: 'Test-generation agents — parallel with Phase 4',
    how: 'Per generated file after Phase 4: xUnit tests driven by the extracted business rules + the mandatory decimal edge-case matrix. Coverage gating is deterministic, not agent opinion. FileEvents stream each Write so the feed pulses while tests are authored.',
  },
  {
    phase: 'On mismatch',
    name: 'Bugfix-loop agent',
    how: 'Triggered by any parity divergence (Phase 6): triages root cause, fixes code or the shared rulebook when a bug class recurs, re-runs the full regression — never patches blind.',
  },
]

const USER_CONTRACT = [
  'SOLID enforced on generated C# (single responsibility per handler, dependencies inverted via Application ports)',
  'Design patterns where the source structure calls for them — never pattern soup',
  'No spaghetti: layered Clean Architecture, dependency rule inward, no cross-layer shortcuts',
  'Versioned output: every run is a ULID; generated code lands as a versioned commit per run in the target repo',
]

export default function AgenticExecutionModel() {
  return (
    <div className="card">
      <h2>Multi-agent execution model</h2>
      <p className="muted">
        The agentic core is a fleet of single-purpose agents with deterministic
        gates between them — not one chat doing everything. Defined in the
        pipeline skills (<span className="mono">.claude/skills/</span>); wiring
        into the run loop is pending, so status shows SKIPPED until then.
      </p>
      <div className="agent-list">
        {AGENTS.map((a) => (
          <div key={a.phase} className="agent-row">
            <span className="explainer-icon agentic">
              <SparkIcon />
            </span>
            <div>
              <strong>
                {a.phase} — {a.name}
              </strong>
              <p className="muted" style={{ margin: '2px 0 0' }}>
                {a.how}
              </p>
            </div>
          </div>
        ))}
      </div>
      <h3 style={{ marginTop: 16 }}>
        <GearIcon width={12} height={12} /> User quality contract — pending adoption into the Phase 4 prompt
      </h3>
      <ul className="edge-list">
        {USER_CONTRACT.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
      <p className="muted mono" style={{ fontSize: 11, marginBottom: 0 }}>
        Note: design/04 currently specifies "classes mapped 1:1 to COBOL programs"
        as the Phase 4 exit shape — superseded by this Clean Architecture proposal;
        doc revision escalated.
      </p>
    </div>
  )
}
