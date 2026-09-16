/** Step 3 — Architecture Proposal. HITL workshop co-authors the C# shape;
 * numbered accordions 01–05 say what happens next. User 2026-09-15: number
 * them so the flow is structured, and a real human-in-the-loop that can
 * propose re-architecture and recreate the estate. */
import { useEffect, useState } from 'react'
import Accordion from '../components/Accordion'
import ArchitectureWorkshop from '../components/ArchitectureWorkshop'
import AgenticExecutionModel from '../components/AgenticExecutionModel'
import DeliverablesContract from '../components/DeliverablesContract'
import FileTree from '../components/FileTree'
import TypeAndTestContracts from '../components/TypeAndTestContracts'
import { GearIcon, SparkIcon } from '../components/Icons'
import { useRun } from '../hooks/useMigrationEvents'
import { getExtracts } from '../lib/api'
import { PHASES } from '../lib/phases'
import {
  deriveDocumentationTree,
  deriveMapping,
  deriveTargetArchitecture,
  TARGET_ARCHITECTURE,
  TARGET_DOCUMENTATION,
} from '../lib/targetArchitecture'

export default function Step3Architecture() {
  const { intake, fileStatus, architecture, runId, phaseMap } = useRun()
  const shape = architecture.shape
  const [nameByFrom, setNameByFrom] = useState<Record<string, string>>({})
  const phase2 = phaseMap.get('Phase 2')?.status

  useEffect(() => {
    if (!runId) return
    void getExtracts(runId)
      .then((rows) => {
        const next: Record<string, string> = {}
        for (const r of rows) {
          if (r.path && r.suggested_component_name?.trim()) {
            next[r.path] = r.suggested_component_name.trim()
          }
        }
        setNameByFrom(next)
      })
      .catch(() => { /* extracts empty until Phase 2 finishes */ })
  }, [runId, phase2])

  const proposedTree = intake ? deriveTargetArchitecture(intake.tree, shape, architecture.directive, nameByFrom) : TARGET_ARCHITECTURE
  const docTree = intake ? deriveDocumentationTree(intake.tree, shape, architecture.directive, nameByFrom) : TARGET_DOCUMENTATION
  const mapping = intake ? deriveMapping(intake.tree, shape, nameByFrom).mappings : []

  return (
    <div>
      <ArchitectureWorkshop />

      <div className="card">
        <h2>Before / after</h2>
        <p className="muted">
          Whole-project reshape for a C# <strong>backend</strong> — Clean Architecture
          use cases, not a 1:1 file translation, and <strong>no web UI</strong>.
          <code>.Application</code> is the use-case layer (handlers), not a frontend app.
          Host is <code>.Cli</code>. Recreate estate redraws this tree from your shape.
        </p>
        <div className="tree-compare">
          <div className="tree-panel">
            <h3>Before — COBOL</h3>
            {intake ? (
              <FileTree
                tree={intake.tree}
                fileStatus={fileStatus}
                storageKey="cobalt.tree.original.arch"
                defaultExpandAll
                inspect="source"
              />
            ) : (
              <p className="muted">No intake yet.</p>
            )}
          </div>
          <div className="tree-panel">
            <h3>After — C# backend ({shape})</h3>
            <FileTree
              tree={proposedTree}
              storageKey={`cobalt.tree.proposed.${shape}`}
              defaultExpandAll
              inspect="proposal"
              mappings={mapping}
            />
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Documentation ontology</h2>
        <p className="muted tree-doc-hint">
          Structured markdown knowledge graph. Agents open
          docs/ontology/GRAPH.md first (A-box), then one node path.
          SCHEMA.md is the T-box. Instance READMEs live next to the code they
          describe — never dump module bodies into the graph.
        </p>
        <div className="table-scroll">
          <table className="contract-table ontology-legend">
            <thead>
              <tr>
                <th>Type</th>
                <th>id</th>
                <th>File</th>
                <th>Role</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Schema</td>
                <td className="mono">schema</td>
                <td className="mono">docs/ontology/SCHEMA.md</td>
                <td>T-box — classes and relations</td>
              </tr>
              <tr>
                <td>Graph</td>
                <td className="mono">graph</td>
                <td className="mono">docs/ontology/GRAPH.md</td>
                <td>A-box — nodes + edges. Agent entry.</td>
              </tr>
              <tr>
                <td>Context</td>
                <td className="mono">ctx</td>
                <td className="mono">docs/ontology/CONTEXT.md</td>
                <td>Bounded context of the migrated system</td>
              </tr>
              <tr>
                <td>Module</td>
                <td className="mono">mod.*</td>
                <td className="mono">src/{'{Layer}'}/README.md</td>
                <td>Clean Architecture layer</td>
              </tr>
              <tr>
                <td>UseCase</td>
                <td className="mono">uc.*</td>
                <td className="mono">UseCases/{'{Name}'}/README.md</td>
                <td>One COBOL program → handler</td>
              </tr>
              <tr>
                <td>Provenance</td>
                <td className="mono">cob.*</td>
                <td className="mono">docs/ontology/provenance/{'{Name}'}.md</td>
                <td>Source program, PIC, CALL sites</td>
              </tr>
              <tr>
                <td>Invariant</td>
                <td className="mono">inv.*</td>
                <td className="mono">docs/ontology/invariants/</td>
                <td>Must-not-break rule, traced to a UseCase</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="muted tree-doc-hint">
          Relations on every node: part_of, implements, depends_on, governs.
          GRAPH.md is the only file an agent must read to pick the next MD.
        </p>
        <div className="tree-panel tree-panel-wide">
          <FileTree
            tree={docTree}
            storageKey={`cobalt.tree.docs.${shape}`}
            defaultExpandAll
            inspect="proposal"
            mappings={mapping}
          />
        </div>
      </div>

      <ol className="happen-rail">
        <li><strong>01</strong> Map every COBOL file to a C# target</li>
        <li><strong>02</strong> Agents convert in dependency waves</li>
        <li><strong>03</strong> Decimal types + coverage gates</li>
        <li><strong>04</strong> English docs + ontology graph</li>
        <li><strong>05</strong> Nine pipeline phases, then tests</li>
      </ol>

      <Accordion n={1} title="File mapping" hint={`${mapping.length} targets · ${shape}`}>
        <ul className="mapping-list">
          {mapping.map((m) => (
            <li key={`${m.from}→${m.to}`} className="mono">
              {m.from} <span className="muted">→</span> {m.to}{' '}
              <span className={`map-kind ${m.kind}`}>{m.kind}</span>
            </li>
          ))}
        </ul>
      </Accordion>

      <Accordion n={2} title="Multi-agent execution" hint="4 agent kinds · deterministic gates">
        <AgenticExecutionModel />
      </Accordion>

      <Accordion n={3} title="Types & tests" hint="decimal contract · coverage gates">
        <TypeAndTestContracts />
      </Accordion>

      <Accordion n={4} title="Final deliverables" hint="GRAPH A-box · SCHEMA T-box">
        <DeliverablesContract />
      </Accordion>

      <Accordion n={5} title="Pipeline phases" hint="9 phases · grey deterministic / violet agentic">
        <div className="phase-order">
          {PHASES.map((p, i) => (
            <span key={p.id} className={`phase-pill ${p.agentic ? 'agentic' : ''}`}>
              {p.agentic ? (
                <SparkIcon width={11} height={11} />
              ) : (
                <GearIcon width={11} height={11} />
              )}
              P{i} {p.label}
            </span>
          ))}
        </div>
      </Accordion>
    </div>
  )
}
