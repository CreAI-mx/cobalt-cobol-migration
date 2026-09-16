/** Brief copy for proposed C# / docs files that do not exist on disk yet.
 * Importer: FilePeek.tsx. No API. Schema: FileMapping.to → copy.
 * User: "en el destino como una descripcion si agentica pero breve, no
 * construiremos aun nada de archivos, solo descripcion breve de lo que habra ahi." */
import type { FileMapping } from './targetArchitecture'

export interface ProposedBrief {
  role: string
  origin?: string
  body: string
}

function firstRule(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim().slice(0, 180)
  if (value && typeof value === 'object') {
    const rec = value as Record<string, unknown>
    for (const k of ['rule', 'text', 'description', 'name']) {
      if (typeof rec[k] === 'string' && rec[k].trim()) return String(rec[k]).trim().slice(0, 180)
    }
  }
  return null
}

export function briefForProposed(
  relPath: string,
  mappings: FileMapping[],
  extract?: { suggested_component_name?: string | null; business_rules?: unknown[] } | null,
): ProposedBrief {
  const name = relPath.split('/').pop() ?? relPath
  const hit = mappings.find((m) => m.to === relPath)
  const origin = hit?.from
  const from = origin ? ` Traces from ${origin}.` : ''
  const extractLine = extract?.suggested_component_name
    ? ` Phase 2 suggested name: ${extract.suggested_component_name}.`
    : ''
  const rule = extract?.business_rules?.map(firstRule).find(Boolean)
  const ruleLine = rule ? ` Extracted rule: ${rule}` : ''

  if (relPath.includes('ontology/GRAPH.md') || name === 'GRAPH.md') {
    return {
      role: 'A-box · agent entry',
      body: 'Typed nodes and edges only. Coding agents start here, then open one path. Assembled after conversion, not written yet.',
    }
  }
  if (relPath.includes('ontology/SCHEMA.md') || name === 'SCHEMA.md') {
    return {
      role: 'T-box',
      body: 'Classes, relations, and constraints for the markdown ontology. Written with GRAPH.md after handlers exist. Not on disk yet.',
    }
  }
  if (relPath.includes('ontology/CONTEXT.md') || name === 'CONTEXT.md') {
    return {
      role: 'Bounded context',
      body: 'One-page description of the migrated system boundary. Documentation assembly, not conversion. Not on disk yet.',
    }
  }
  if (relPath.includes('ontology/provenance/')) {
    return {
      role: 'COBOL provenance',
      origin,
      body: `Source PROGRAM-ID, PIC clauses, CALL sites for this program.${from} Written during doc assembly. Not on disk yet.`,
    }
  }
  if (relPath.includes('ontology/invariants')) {
    return {
      role: 'Invariant index',
      body: 'Must-not-break rules traced to use cases. Filled after conversion. Not on disk yet.',
    }
  }
  if (name === 'DOCUMENTATION.md' || name === 'documentation-master.md') {
    return {
      role: 'Agent reading map',
      body: 'Derived from GRAPH.md. Points agents at instance READMEs. Not a dump of module bodies. Not on disk yet.',
    }
  }
  if (name === 'ARCHITECTURE.md' || name === 'ONBOARDING.md' || name === 'CONVERSION-NOTES.md') {
    return {
      role: 'Human doc',
      body: `${name} for operators. English, factual. Assembled after Phase 4 handlers exist. Not on disk yet.`,
    }
  }
  if (relPath.startsWith('docs/source/') || hit?.kind === 'doc') {
    return {
      role: 'Carried source doc',
      origin,
      body: `Copied from the COBOL-era tree so it never collides with generated GRAPH/README.${from} Not rewritten.`,
    }
  }
  if (relPath.startsWith('app-here/') || name === 'app-here') {
    return {
      role: 'App placeholder',
      body: 'App here. Empty folder only — Cobalt does not generate a web UI. Fill this yourself if you need a client.',
    }
  }
  if (hit?.kind === 'asset' || relPath.startsWith('assets/')) {
    return {
      role: 'Carried asset',
      origin,
      body: `Non-COBOL file kept as-is under assets/.${from} Copied, not translated.`,
    }
  }
  if (name.endsWith('.sln')) {
    return {
      role: 'Solution',
      body: 'Deterministic scaffold after conversion waves. Empty until Phase 4 writes projects. Not on disk yet.',
    }
  }
  if (name.endsWith('.csproj')) {
    return {
      role: 'Project file',
      body: 'Minimal csproj so generated .cs files compile. Scaffolded after waves, never LLM-authored. Not on disk yet.',
    }
  }
  if (name === 'Program.cs') {
    return {
      role: 'CLI composition root',
      body: 'Wires ports to adapters and starts the console host. Banking backend only — no web UI, no SPA. Not generated yet.',
    }
  }
  if (name.endsWith('Handler.cs') || (hit?.kind === 'use-case' && name.endsWith('.cs'))) {
    return {
      role: 'Use case',
      origin,
      body: `C# handler for one COBOL program in the backend use-case layer (not a GUI). PIC V99 → decimal. Behavior from Phase 2, not a 1:1 transliteration.${from}${extractLine}${ruleLine} Phase 4 writes this. Not on disk yet.`,
    }
  }
  if (/^I.+Port\.cs$/.test(name)) {
    return {
      role: 'Application port',
      origin,
      body: `Inbound port next to the handler. Infrastructure implements it. Dependency rule points inward.${from} Not on disk yet.`,
    }
  }
  if (name.endsWith('Tests.cs') || relPath.includes('.Tests/')) {
    return {
      role: 'Test class',
      origin,
      body: `xUnit tests for the matching handler, including the decimal edge-case matrix. Authored in Phase 5 after conversion.${from}`,
    }
  }
  if (name === 'README.md' && (hit?.kind === 'module-doc' || relPath.includes('UseCases/'))) {
    return {
      role: 'Use-case README',
      origin,
      body: `Agent README: YAML frontmatter (uc.*, implements cob.*) then ≤60 lines. Same Phase 4 turn as the handler.${from} Not on disk yet.`,
    }
  }
  if (name === 'README.md') {
    return {
      role: 'Layer README',
      body: 'Short agent README for this folder. Ontological frontmatter + what a later agent must not break. Written at doc assembly. Not on disk yet.',
    }
  }
  if (hit?.kind === 'value-object' || relPath.includes('ValueObjects/')) {
    return {
      role: 'Value object',
      origin,
      body: `Domain type from a copybook. PIC implied decimals map to C# decimal, never float.${from} Not on disk yet.`,
    }
  }
  return {
    role: 'Proposed file',
    origin,
    body: `Placeholder in the target estate. Nothing has been written here yet.${from}`,
  }
}