/** Live construction tags for the After C# tree on Step 5.
 * Importers: Step5Migrate.tsx, FileTree.tsx (via tags Map).
 * No backend schema change — reads existing SSE FileEvents + FileMapping.
 * User (verbatim): "que se vea que se demuestre que se va construyendo de la
 * arquitectura ... con etiquetas, todo in progres, tested, donde etc" and
 * "en le ultimo paso sigen sin haber animaciones tipo loaders". */
import type { MigrationEvent, PhaseEvent, RunStatus, TreeNode, WorkItem } from './api'
import type { FileMapping } from './targetArchitecture'

export type BuildTag =
  | 'pending'
  | 'in-progress'
  | 'testing'
  | 'done'
  | 'tested'
  | 'bugfix'
  | 'skipped'

export const BUILD_TAG_LABEL: Record<BuildTag, string> = {
  pending: 'To do',
  'in-progress': 'In progress',
  testing: 'Testing',
  done: 'Done',
  tested: 'Tested',
  bugfix: 'Bugfix',
  skipped: 'Skipped',
}

const DEST_PREFIX = /^(src|tests|docs|assets)\//
const COBOL_SRC = /\.(cob|cbl)$/i
const FILE_TAG_PHASES = new Set([
  'Phase 4',
  'Phase 5',
  'Generating',
  'Building',
  'Repairing',
  'Testing',
  'Parity Validation',
  'Documenting',
])

function isTestPhase(phase: string): boolean {
  return phase === 'Phase 5' || phase === 'Testing'
}

export function normalizePath(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\.\//, '')
}

export function collectTreeFiles(node: TreeNode, prefix = '', out: string[] = []): string[] {
  for (const c of node.children ?? []) {
    const path = prefix ? `${prefix}/${c.name}` : c.name
    if (c.type === 'dir') collectTreeFiles(c, path, out)
    else out.push(path)
  }
  return out
}

function unique(paths: string[]): string[] {
  return [...new Set(paths.map(normalizePath).filter(Boolean))]
}

function isDestPath(path: string): boolean {
  const p = normalizePath(path)
  if (COBOL_SRC.test(p)) return false
  return DEST_PREFIX.test(p) || p === 'README.md' || /\.(cs|csproj|sln)$/i.test(p)
}

/** Exact dest only. Never stamp every README.md because one event said README.md. */
function pinToTree(path: string, files: string[]): string[] {
  const p = normalizePath(path)
  if (files.includes(p)) return [p]
  const suffix = files.filter((f) => f.endsWith(`/${p}`))
  return suffix.length === 1 ? suffix : []
}

function destsFor(
  filePath: string,
  detail: string,
  mappings: FileMapping[],
  files: string[],
  running: boolean,
): string[] {
  const path = normalizePath(filePath)
  const out: string[] = []
  if (isDestPath(path)) out.push(...pinToTree(path, files))

  if (COBOL_SRC.test(path) || mappings.some((m) => normalizePath(m.from) === path)) {
    const maps = mappings.filter((m) => {
      const from = normalizePath(m.from)
      return from === path || from.endsWith(`/${path}`)
    })
    if (running) {
      const handler = maps.find((m) => m.kind === 'use-case') ?? maps[0]
      if (handler) out.push(normalizePath(handler.to))
    } else {
      for (const m of maps) out.push(normalizePath(m.to))
    }
  }

  const list = detail.match(/(?:written|test file\(s\)):\s*(.+)$/i)
  if (list) {
    for (const p of list[1].split(',')) {
      const t = p.trim()
      if (t) out.push(...pinToTree(t, files))
    }
  }
  return unique(out).filter((d) => files.includes(d))
}

export function isWaitingPhase(ev: PhaseEvent | undefined, action?: string): boolean {
  if (!ev || ev.status !== 'RUNNING' || !/^WAITING/i.test(ev.detail)) return false
  // Accept already stored — do not keep the WAITING chip just because the last
  // SSE frame is still the pre-accept notice.
  return action !== 'accepted'
}

export function deriveEstateStatus(
  events: MigrationEvent[],
  mappings: FileMapping[],
  proposed: TreeNode,
  _phaseMap: Map<string, PhaseEvent>,
): Map<string, BuildTag> {
  const files = collectTreeFiles(proposed)
  const tags = new Map<string, BuildTag>()
  for (const f of files) tags.set(f, 'pending')

  const handlerToTests = new Map<string, string[]>()
  for (const m of mappings.filter((x) => x.kind === 'use-case')) {
    const to = normalizePath(m.to)
    const stem = (to.split('/').pop() ?? '').replace(/Handler\.cs$/, '').replace(/\.cs$/, '')
    const test = files.find((f) => f.endsWith(`${stem}HandlerTests.cs`) || f.endsWith(`${stem}Tests.cs`))
    if (test) handlerToTests.set(to, [test])
  }

  for (const e of events) {
    if (e.type !== 'file') continue
    if (!FILE_TAG_PHASES.has(e.phase)) continue
    const raw = e.status.toUpperCase()
    const running = raw === 'RUNNING'
    const dests = destsFor(e.file_path, e.detail, mappings, files, running)
    let tag: BuildTag | null = null
    if (running) tag = isTestPhase(e.phase) ? 'testing' : 'in-progress'
    else if (raw === 'FAILED' || raw === 'BLOCKED') tag = 'bugfix'
    else if (raw === 'SKIPPED') tag = 'skipped'
    else if (raw === 'OK' || raw === 'DONE' || raw === 'PASSED') {
      tag = isTestPhase(e.phase) ? 'tested' : 'done'
    }
    if (!tag) continue
    for (const d of dests) {
      tags.set(d, tag)
      if (tag === 'tested') {
        for (const t of handlerToTests.get(d) ?? []) tags.set(t, 'tested')
      }
      if (tag === 'testing') {
        for (const t of handlerToTests.get(d) ?? []) tags.set(t, 'testing')
      }
    }
  }

  return tags
}

export function folderTally(
  node: TreeNode,
  prefix: string,
  tags: Map<string, BuildTag>,
): { todo: number; live: number; testing: number; done: number; bugfix: number; total: number } {
  const tally = { todo: 0, live: 0, testing: 0, done: 0, bugfix: 0, total: 0 }
  const walk = (n: TreeNode, pre: string) => {
    for (const c of n.children ?? []) {
      const path = pre ? `${pre}/${c.name}` : c.name
      if (c.type === 'dir') walk(c, path)
      else {
        tally.total += 1
        const t = tags.get(path) ?? 'pending'
        if (t === 'in-progress') tally.live += 1
        else if (t === 'testing') tally.testing += 1
        else if (t === 'done' || t === 'tested' || t === 'skipped') tally.done += 1
        else if (t === 'bugfix') tally.bugfix += 1
        else tally.todo += 1
      }
    }
  }
  walk(node, prefix)
  return tally
}

export function countTags(tags: Map<string, BuildTag>): Record<BuildTag, number> {
  const counts: Record<BuildTag, number> = {
    pending: 0,
    'in-progress': 0,
    testing: 0,
    done: 0,
    tested: 0,
    bugfix: 0,
    skipped: 0,
  }
  for (const t of tags.values()) counts[t] += 1
  return counts
}

export interface EstateProgress {
  total: number
  done: number
  tested: number
  inProgress: number
  testing: number
  bugfix: number
  skipped: number
  remaining: number
  finished: number
  pct: number
}

export function estateProgress(counts: Record<BuildTag, number>): EstateProgress {
  const total = Object.values(counts).reduce((n, v) => n + v, 0)
  const remaining = counts.pending
  const finished = counts.done + counts.tested + counts.skipped
  const pct = total === 0 ? 0 : Math.round((finished / total) * 100)
  return {
    total,
    done: counts.done,
    tested: counts.tested,
    inProgress: counts['in-progress'],
    testing: counts.testing,
    bugfix: counts.bugfix,
    skipped: counts.skipped,
    remaining,
    finished,
    pct,
  }
}

export function inProgressPaths(tags: Map<string, BuildTag>): string[] {
  const out: string[] = []
  for (const [path, tag] of tags) {
    if (tag === 'in-progress' || tag === 'testing') out.push(path)
  }
  return out
}

/** Last Phase 4/5 RUNNING dest that still has a live tag — header + scroll target. */
export function latestBuildPath(
  events: MigrationEvent[],
  tags: Map<string, BuildTag>,
): string | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    if (e.type !== 'file') continue
    if (!FILE_TAG_PHASES.has(e.phase)) continue
    if (e.status.toUpperCase() !== 'RUNNING') continue
    const path = normalizePath(e.file_path)
    const tagged = tags.get(path)
    if (tagged === 'in-progress' || tagged === 'testing') return path
    for (const [p, t] of tags) {
      if ((t === 'in-progress' || t === 'testing') && (p === path || p.endsWith(`/${path}`))) {
        return p
      }
    }
  }
  return inProgressPaths(tags).at(-1) ?? null
}

export function phaseIsWaiting(
  phaseMap: Map<string, PhaseEvent>,
  id = 'Phase 4',
  action?: string,
): boolean {
  return isWaitingPhase(phaseMap.get(id), action)
}

/** Real "After" tree for the work-item orchestrator: built from the plan's own
 * expected_paths, not a client-side guess of what Clean Architecture "should"
 * produce. User (verbatim, 2026-09-15): a PASSED run showed "33%" and dozens
 * of per-folder README.md/csproj/.sln rows stuck on "To do" forever, because
 * the old predicted tree (targetArchitecture.ts) invents files the real
 * work-item plan never declares. This has none of that — only real files. */
export function treeFromPaths(paths: string[]): TreeNode {
  const root: TreeNode = { name: 'root', type: 'dir', is_cobol: false, children: [] }
  for (const raw of paths) {
    const parts = normalizePath(raw).split('/').filter(Boolean)
    let node = root
    parts.forEach((part, i) => {
      const isLeaf = i === parts.length - 1
      const existing = node.children?.find((c) => c.name === part)
      const child: TreeNode =
        existing ??
        { name: part, type: isLeaf ? 'file' : 'dir', is_cobol: false, children: isLeaf ? null : [] }
      if (!existing) {
        node.children = node.children ?? []
        node.children.push(child)
      }
      node = child
    })
  }
  return root
}

export interface PlanBuildTagsOptions {
  phaseMap?: Map<string, PhaseEvent>
  runStatus?: RunStatus | null
  workItems?: WorkItem[]
  planStage?: string
  finishedAt?: string | null
  live?: boolean
}

function runIsComplete(options?: PlanBuildTagsOptions): boolean {
  if (options?.live) return false
  if (options?.runStatus === 'FAILED' || options?.runStatus === 'ABORTED') return false
  if (options?.runStatus === 'PASSED') return true
  if (options?.planStage === 'completed') return true
  const testing = options?.phaseMap?.get('Testing')
  const documenting = options?.phaseMap?.get('Documenting')
  if (testing?.status === 'OK' && documenting?.status === 'OK') return true
  return false
}

function testsGatePassed(options?: PlanBuildTagsOptions): boolean {
  if (options?.planStage === 'completed') return true
  const testing = options?.phaseMap?.get('Testing')
  return testing?.status === 'OK' && /pass/i.test(testing.detail ?? '')
}

function applyTestedTags(tags: Map<string, BuildTag>): void {
  for (const [path, tag] of tags) {
    if (/Tests\.cs$/i.test(path) || /Tests\.csproj$/i.test(path)) {
      tags.set(path, 'tested')
    } else if (tag === 'done' && /\.cs$/i.test(path)) {
      tags.set(path, 'tested')
    }
  }
}

function resolvePlanPath(raw: string, tags: Map<string, BuildTag>): string | null {
  const path = normalizePath(raw)
  if (tags.has(path)) return path
  const keys = [...tags.keys()]
  const matches = keys.filter((k) => k === path || k.endsWith(`/${path}`) || path.endsWith(k))
  return matches.length === 1 ? matches[0] : null
}

/** Build tags for treeFromPaths' output, driven only by real FileEvents for
 * paths the plan actually declared — no prediction, no placeholder rows. */
export function planBuildTags(
  expectedPaths: string[],
  events: MigrationEvent[],
  options?: PlanBuildTagsOptions,
): Map<string, BuildTag> {
  const tags = new Map<string, BuildTag>()
  for (const p of expectedPaths) tags.set(normalizePath(p), 'pending')

  for (const e of events) {
    if (e.type !== 'file') continue
    const resolved = resolvePlanPath(e.file_path ?? '', tags)
    if (!resolved) continue
    const status = (e.status ?? '').toUpperCase()
    const testPhase = isTestPhase(e.phase)
    const cur = tags.get(resolved)

    if (status === 'RUNNING') {
      if (cur !== 'done' && cur !== 'tested' && cur !== 'skipped') {
        tags.set(resolved, testPhase ? 'testing' : 'in-progress')
      }
    } else if (status === 'FAILED' || status === 'BLOCKED') {
      tags.set(resolved, 'bugfix')
    } else if (status === 'SKIPPED') {
      tags.set(resolved, 'skipped')
    } else if (status === 'OK' || status === 'DONE' || status === 'PASSED') {
      tags.set(resolved, testPhase ? 'tested' : 'done')
    }
  }

  for (const item of options?.workItems ?? []) {
    if (item.status !== 'completed') continue
    for (const p of item.expected_paths) {
      const path = normalizePath(p)
      const cur = tags.get(path)
      if (cur === 'pending' || cur === 'in-progress' || cur === 'testing') {
        tags.set(path, item.kind === 'tests' ? 'tested' : 'done')
      }
    }
  }

  const documentingEv = options?.phaseMap?.get('Documenting')
  if (documentingEv?.status === 'OK') {
    for (const path of tags.keys()) {
      if (/README\.md$/i.test(path) || /MIGRATION\.md$/i.test(path)) {
        const cur = tags.get(path)
        if (cur === 'pending' || cur === 'in-progress') tags.set(path, 'done')
      }
    }
  }

  if (runIsComplete(options)) {
    for (const [path, tag] of tags) {
      if (tag === 'pending' || tag === 'in-progress' || tag === 'testing') {
        tags.set(path, 'done')
      }
    }
  }

  if (testsGatePassed(options)) applyTestedTags(tags)

  return tags
}
