/** PROPOSED target C# architecture — NOT a 1:1 file translation (user
 * requirement 2026-09-15: "no busco la migración 1:1"). The proposal is a
 * Clean Architecture re-shape: COBOL programs become use cases in the
 * Application layer (backend handlers — not a GUI). Copybooks become Domain
 * value objects. Host is a CLI. No web/SPA is generated.
 *
 * Documentation contract (user 2026-09-15): root README.md is for humans;
 * docs/DOCUMENTATION.md is the agent Documentation Master (index only);
 * each module and submodule ships its own README.md so an agent jumps to
 * one file without reading the tree. Importers: Step3Architecture.tsx.
 * FileMapping.kind adds `module-doc`; no backend schema change.
 *
 * Honesty note: naming here is a deterministic derivation from file names
 * (snake_case -> PascalCase); the genuinely AGENTIC refinement (LLM reading
 * program logic to name entities and use cases from behavior, not filenames)
 * is Phase 2/4 work, still stubbed — the UI labels this accordingly.
 * `is_cobol: true` is reused as the row-emphasis flag (see FileTree). */
import type { TreeNode } from './api'

const file = (name: string, emphasized = false): TreeNode => ({
  name,
  type: 'file',
  is_cobol: emphasized,
  children: null,
})

const dir = (name: string, children: TreeNode[]): TreeNode => ({
  name,
  type: 'dir',
  is_cobol: false,
  children,
})

const readme = (emphasized = false): TreeNode => file('README.md', emphasized)

export type ArchShape = 'clean' | 'per-program' | 'one-to-one'

export const ARCH_SHAPES: Array<{ id: ArchShape; label: string; blurb: string }> = [
  {
    id: 'clean',
    label: 'Clean Architecture',
    blurb: 'Backend layers + one use-case per COBOL program. CLI host, no web UI.',
  },
  {
    id: 'per-program',
    label: 'Modular monolith',
    blurb: 'One C# project per COBOL program — maps CALL boundaries 1:1 to projects.',
  },
  {
    id: 'one-to-one',
    label: 'Keep COBOL folders',
    blurb: 'Same tree, .cob → .cs. Only if the human explicitly asks for 1:1 paths.',
  },
]

export function docMasterName(directive = ''): string {
  const tagged = directive.match(/\[doc-master:\s*([A-Za-z0-9._-]+\.md)\]/i)
  if (tagged) return tagged[1]
  const names = [...directive.matchAll(/([A-Za-z0-9._-]+\.md)/gi)].map((m) => m[1])
  for (const n of names) {
    // Typos like "docuemntation-master.md" still mean the agent reading map.
    if (/doc/i.test(n) && /master/i.test(n)) return 'documentation-master.md'
  }
  if (/documentation[-_]?master/i.test(directive)) return 'documentation-master.md'
  return 'DOCUMENTATION.md'
}

/** Fold a Corrections comment into the architecture directive. Known transform:
 * rename the agent doc master when the human asks for documentation-master.md. */
export function mergeCorrectionDirective(existing: string, comment: string): string {
  const bits: string[] = []
  const prev = existing.trim()
  const req = comment.trim()
  if (prev) bits.push(prev)
  const master = docMasterName(req)
  if (master !== 'DOCUMENTATION.md' && !/\[doc-master:/i.test(prev)) {
    bits.push(`[doc-master: ${master}]`)
  }
  if (req && !prev.includes(req)) bits.push(req)
  return bits.join('\n')
}

export interface FileMapping {
  from: string
  to: string
  kind: 'use-case' | 'value-object' | 'doc' | 'asset' | 'module-doc'
}

const COBOL_PROGRAM_EXTS = ['.cob', '.cbl']
const COPYBOOK_EXTS = ['.cpy']
const DOC_EXTS = ['.md', '.txt', '.adoc', '.rst']
const FRONT_EXTS = ['.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.vue', '.css', '.scss', '.sass', '.html', '.htm', '.map']
const FRONT_NAMES = new Set([
  'package.json',
  'package-lock.json',
  'yarn.lock',
  'pnpm-lock.yaml',
  'bun.lockb',
  'tsconfig.json',
  'jsconfig.json',
])

function ext(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

/** transaction_posting.cbl -> TransactionPosting */
function pascalStem(name: string): string {
  const stem = name.replace(/\.[^.]+$/, '')
  return stem
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
    .join('')
}

function collectFiles(node: TreeNode, prefix: string, out: Array<{ path: string; name: string }>) {
  for (const c of node.children ?? []) {
    const path = prefix ? `${prefix}/${c.name}` : c.name
    if (c.type === 'dir') collectFiles(c, path, out)
    else out.push({ path, name: c.name })
  }
}

function isFrontendArtifact(name: string, path: string): boolean {
  if (FRONT_NAMES.has(name.toLowerCase())) return true
  if (FRONT_EXTS.includes(ext(name))) return true
  return /(^|\/)(node_modules|\.next|frontend|web-ui|client)(\/|$)/i.test(path)
}

function sanitizeBackendSln(raw: string): string {
  // node-accounting-app → AccountingSystem. Never keep App/Web — this estate is
  // a C# backend, not a frontend (user: "esto es solo para backend nada de front").
  const stripped = raw
    .replace(/^(node|nodejs|react|vue|angular|next|nuxt|frontend|web|ui|client)[-._]*/i, '')
    .replace(/[-._]*(app|application|frontend|webapp|web|ui|client|spa|gui)$/i, '')
  const p = pascalStem(stripped)
  if (!p || /^(App|Web|Ui|Client|Node)$/i.test(p)) return 'AccountingSystem'
  return /system$/i.test(p) ? p : `${p}System`
}

/** Solution name from the COBOL estate, never from a Node/web app folder. */
function solutionName(tree: TreeNode): string {
  const dirs = (tree.children ?? []).filter((c) => c.type === 'dir')
  const pick =
    dirs.find((d) => !/^(node|frontend|web|ui|client|app)/i.test(d.name)) ?? dirs[0]
  return sanitizeBackendSln(pick?.name ?? 'AccountingSystem')
}

function cobolDest(shape: ArchShape, sln: string, path: string, p: string): { handler: string; readme: string } {
  if (shape === 'per-program') {
    return {
      handler: `src/${sln}.${p}/${p}.cs`,
      readme: `src/${sln}.${p}/README.md`,
    }
  }
  if (shape === 'one-to-one') {
    const dir = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : ''
    const stem = path.replace(/\.[^.]+$/, '')
    return {
      handler: `${stem}.cs`,
      readme: dir ? `${dir}/README.md` : 'README.md',
    }
  }
  return {
    handler: `src/${sln}.Application/UseCases/${p}/${p}Handler.cs`,
    readme: `src/${sln}.Application/UseCases/${p}/README.md`,
  }
}

/** Destination of every intake file. Default is Clean Architecture (not 1:1);
 * HITL can switch to per-program projects or keep COBOL folders. */
export function deriveMapping(
  intakeTree: TreeNode,
  shape: ArchShape = 'clean',
  nameByFrom: Record<string, string> = {},
): { sln: string; mappings: FileMapping[] } {
  const files: Array<{ path: string; name: string }> = []
  collectFiles(intakeTree, '', files)
  const sln = solutionName(intakeTree)

  const mappings: FileMapping[] = []
  for (const { path, name } of files) {
    if (isFrontendArtifact(name, path)) continue
    const e = ext(name)
    const p = nameByFrom[path]?.trim() || pascalStem(name)
    if (COBOL_PROGRAM_EXTS.includes(e)) {
      const dest = cobolDest(shape, sln, path, p)
      mappings.push({ from: path, to: dest.handler, kind: 'use-case' })
      mappings.push({ from: path, to: dest.readme, kind: 'module-doc' })
      continue
    }
    if (COPYBOOK_EXTS.includes(e)) {
      const vo =
        shape === 'one-to-one'
          ? path.replace(/\.[^.]+$/, '.cs')
          : shape === 'per-program'
            ? `src/${sln}.Shared/${p}.cs`
            : `src/${sln}.Domain/ValueObjects/${p}.cs`
      mappings.push({ from: path, to: vo, kind: 'value-object' })
      continue
    }
    if (DOC_EXTS.includes(e)) {
      mappings.push({ from: path, to: `docs/source/${name}`, kind: 'doc' })
      continue
    }
    mappings.push({ from: path, to: `assets/${path}`, kind: 'asset' })
  }
  return { sln, mappings }
}

function generatedDocTree(
  sourceDocs: FileMapping[],
  _useCases: FileMapping[],
  master = 'DOCUMENTATION.md',
): TreeNode {
  // Matches real backend output (llm.py _DOC_PROMPT_TEMPLATE / orchestrator.py
  // documentation work item, simplified 2026-09-15): exactly README.md (repo
  // root, rendered by the caller) + one master doc under docs/ — no ontology,
  // no per-use-case provenance, no invariants tree. This preview must track
  // what the pipeline actually writes, not a design that was cut.
  const children: TreeNode[] = [file(master)]
  if (sourceDocs.length > 0) {
    children.push(
      dir(
        'source',
        sourceDocs.map((m) => file(m.from.split('/').pop() ?? m.from)),
      ),
    )
  }
  return dir('docs', children)
}

function stemOf(m: FileMapping): string {
  return pascalStem(m.from.split('/').pop() ?? m.from)
}

function treeFromDestinations(rootName: string, dests: string[], extra: TreeNode[]): TreeNode {
  const children: TreeNode[] = []
  const insert = (nodes: TreeNode[], parts: string[]) => {
    if (parts.length === 0) return
    if (parts.length === 1) {
      if (!nodes.some((n) => n.name === parts[0] && n.type === 'file')) {
        nodes.push(file(parts[0], true))
      }
      return
    }
    let folder = nodes.find((n) => n.name === parts[0] && n.type === 'dir')
    if (!folder) {
      folder = dir(parts[0], [])
      nodes.push(folder)
    }
    insert(folder.children ?? [], parts.slice(1))
  }
  for (const dest of dests) insert(children, dest.split('/').filter(Boolean))
  children.push(...extra)
  return dir(rootName, children)
}

function derivePerProgramTree(sln: string, mappings: FileMapping[], master: string): TreeNode {
  const useCases = mappings.filter((m) => m.kind === 'use-case')
  const valueObjects = mappings.filter((m) => m.kind === 'value-object')
  const docs = mappings.filter((m) => m.kind === 'doc')
  const assets = mappings.filter((m) => m.kind === 'asset')
  const projects = useCases.map((m) => {
    const p = stemOf(m)
    return dir(`${sln}.${p}`, [readme(true), file(`${p}.cs`, true), file(`${sln}.${p}.csproj`)])
  })
  const src: TreeNode[] = []
  if (valueObjects.length > 0) {
    src.push(
      dir(`${sln}.Shared`, [
        readme(true),
        ...valueObjects.map((m) => file(`${stemOf(m)}.cs`, true)),
        file(`${sln}.Shared.csproj`),
      ]),
    )
  }
  src.push(...projects)
  const root: TreeNode[] = [readme(true), dir('src', src), generatedDocTree(docs, useCases, master)]
  if (assets.length > 0) {
    root.push(dir('assets', assets.map((m) => file(m.from.split('/').pop() ?? m.from))))
  }
  root.push(file(`${sln}.sln`))
  return dir(sln, root)
}

function deriveOneToOneTree(sln: string, mappings: FileMapping[], master: string): TreeNode {
  const useCases = mappings.filter((m) => m.kind === 'use-case')
  const docs = mappings.filter((m) => m.kind === 'doc')
  const dests = mappings.filter((m) => m.kind !== 'doc').map((m) => m.to)
  return treeFromDestinations(sln, dests, [
    generatedDocTree(docs, useCases, master),
    file(`${sln}.sln`),
  ])
}

/** Render the HITL-chosen shape as a TreeNode for FileTree.
 * Empty layer directories are shown as empty dirs — contents are never fabricated. */
export function deriveTargetArchitecture(
  intakeTree: TreeNode,
  shape: ArchShape = 'clean',
  directive = '',
  nameByFrom: Record<string, string> = {},
): TreeNode {
  const { sln, mappings } = deriveMapping(intakeTree, shape, nameByFrom)
  const master = docMasterName(directive)
  if (shape === 'per-program') return derivePerProgramTree(sln, mappings, master)
  if (shape === 'one-to-one') return deriveOneToOneTree(sln, mappings, master)

  const useCases = mappings.filter((m) => m.kind === 'use-case')
  const valueObjects = mappings.filter((m) => m.kind === 'value-object')
  const docs = mappings.filter((m) => m.kind === 'doc')
  const assets = mappings.filter((m) => m.kind === 'asset')

  const domain = dir(`${sln}.Domain`, [
    readme(true),
    dir('Entities', [readme()]),
    dir('ValueObjects', [readme(), ...valueObjects.map((m) => file(`${stemOf(m)}.cs`, true))]),
    file(`${sln}.Domain.csproj`),
  ])

  const application = dir(`${sln}.Application`, [
    readme(true),
    dir(
      'UseCases',
      useCases.map((m) => {
        const p = stemOf(m)
        return dir(p, [readme(true), file(`${p}Handler.cs`, true), file(`I${p}Port.cs`)])
      }),
    ),
    file(`${sln}.Application.csproj`),
  ])

  const infrastructure = dir(`${sln}.Infrastructure`, [
    readme(true),
    dir('Persistence', [readme()]),
    file(`${sln}.Infrastructure.csproj`),
  ])

  const presentation = dir(`${sln}.Cli`, [
    readme(true),
    file('Program.cs', true),
    file(`${sln}.Cli.csproj`),
  ])

  const tests = dir('tests', [
    dir(`${sln}.Domain.Tests`, [readme(), file(`${sln}.Domain.Tests.csproj`)]),
    dir(`${sln}.Application.Tests`, [
      readme(),
      ...useCases.map((m) => file(`${stemOf(m)}HandlerTests.cs`, true)),
      file(`${sln}.Application.Tests.csproj`),
    ]),
    dir(`${sln}.Integration.Tests`, [
      readme(),
      file('CobolParityTests.cs', true),
      file(`${sln}.Integration.Tests.csproj`),
    ]),
  ])

  const root: TreeNode[] = [
    readme(true),
    dir('src', [domain, application, infrastructure, presentation]),
    tests,
    generatedDocTree(docs, useCases, master),
  ]
  if (assets.length > 0) {
    root.push(dir('assets', assets.map((m) => file(m.from.split('/').pop() ?? m.from))))
  }
  root.push(file(`${sln}.sln`))
  return dir(sln, root)
}

/** Markdown ontology — T-box (SCHEMA) + A-box (GRAPH) + instance READMEs.
 * Agents query GRAPH.md first; they do not ingest sibling bodies.
 * Importer: Step3Architecture.tsx. */
export function deriveDocumentationTree(
  intakeTree: TreeNode,
  shape: ArchShape = 'clean',
  directive = '',
  nameByFrom: Record<string, string> = {},
): TreeNode {
  const { sln, mappings } = deriveMapping(intakeTree, shape, nameByFrom)
  const useCases = mappings.filter((m) => m.kind === 'use-case')
  const sourceDocs = mappings.filter((m) => m.kind === 'doc')
  const stemOf = (m: FileMapping) => pascalStem(m.from.split('/').pop() ?? m.from)
  const master = docMasterName(directive)

  return dir(`${sln} ontology`, [
    readme(true),
    generatedDocTree(sourceDocs, useCases, master),
    dir('src', [
      dir(`${sln}.Domain`, [
        readme(true),
        dir('Entities', [readme()]),
        dir('ValueObjects', [readme()]),
      ]),
      dir(`${sln}.Application`, [
        readme(true),
        dir(
          'UseCases',
          useCases.map((m) => dir(stemOf(m), [readme(true)])),
        ),
      ]),
      dir(`${sln}.Infrastructure`, [readme(true), dir('Persistence', [readme()])]),
      dir(`${sln}.Cli`, [readme(true)]),
    ]),
    dir('tests', [
      dir(`${sln}.Domain.Tests`, [readme()]),
      dir(`${sln}.Application.Tests`, [readme()]),
      dir(`${sln}.Integration.Tests`, [readme()]),
    ]),
  ])
}

/** Static demo fallback — shown only before any intake. Same clean shape. */
export const TARGET_ARCHITECTURE: TreeNode = dir('AccountingSystem', [
  readme(true),
  dir('src', [
    dir('AccountingSystem.Domain', [
      readme(true),
      dir('Entities', [readme(), file('Account.cs', true)]),
      dir('ValueObjects', [readme(), file('Money.cs', true)]),
      file('AccountingSystem.Domain.csproj'),
    ]),
    dir('AccountingSystem.Application', [
      readme(true),
      dir('UseCases', [
        dir('PostTransaction', [
          readme(true),
          file('PostTransactionHandler.cs', true),
        ]),
        dir('ViewBalance', [readme(true), file('ViewBalanceHandler.cs', true)]),
      ]),
      file('AccountingSystem.Application.csproj'),
    ]),
    dir('AccountingSystem.Infrastructure', [
      readme(true),
      dir('Persistence', [readme(), file('InMemoryAccountStore.cs', true)]),
      file('AccountingSystem.Infrastructure.csproj'),
    ]),
    dir('AccountingSystem.Cli', [
      readme(true),
      file('Program.cs', true),
      file('AccountingSystem.Cli.csproj'),
    ]),
  ]),
  dir('tests', [
    dir('AccountingSystem.Application.Tests', [
      readme(),
      file('PostTransactionHandlerTests.cs', true),
      file('AccountingSystem.Application.Tests.csproj'),
    ]),
  ]),
  dir('docs', [file('DOCUMENTATION.md')]),
  file('AccountingSystem.sln'),
])

export const TARGET_DOCUMENTATION: TreeNode = dir('AccountingSystem ontology', [
  readme(true),
  dir('docs', [file('DOCUMENTATION.md')]),
  dir('src', [
    dir('AccountingSystem.Domain', [
      readme(true),
      dir('Entities', [readme()]),
      dir('ValueObjects', [readme()]),
    ]),
    dir('AccountingSystem.Application', [
      readme(true),
      dir('UseCases', [
        dir('PostTransaction', [readme(true)]),
        dir('ViewBalance', [readme(true)]),
      ]),
    ]),
    dir('AccountingSystem.Infrastructure', [
      readme(true),
      dir('Persistence', [readme()]),
    ]),
    dir('AccountingSystem.Cli', [readme(true)]),
  ]),
  dir('tests', [
    dir('AccountingSystem.Application.Tests', [readme()]),
  ]),
])
