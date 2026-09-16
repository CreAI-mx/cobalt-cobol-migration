/** FileTree — spatial view of the same event stream the feed shows (design
 * §Density 2): default collapsed to top-level dirs with per-dir file counts,
 * per-file status dots synced live with FileEvents. Expand state persists per
 * session via sessionStorage. Also reused for the PROPOSED target architecture
 * (static TreeNode, no fileStatus) — `is_cobol` doubles as the row-emphasis
 * flag in that mode.
 * Step 5: `buildTags` paints After-tree construction (pending/in progress/done/tested).
 * Inspect: click a file to FilePeek. Importers: Step1–5. API GET /file.
 * User: modal al click; origen archivo real; destino descripcion breve. */
import { useCallback, useLayoutEffect, useRef, useState } from 'react'
import type { TreeNode } from '../lib/api'
import type { BuildTag } from '../lib/estateBuild'
import { BUILD_TAG_LABEL, folderTally } from '../lib/estateBuild'
import type { FileMapping } from '../lib/targetArchitecture'
import { ChevronIcon, FileIcon, FolderIcon } from './Icons'
import FilePeek from './FilePeek'
import ExplorationDocPeek from './ExplorationDocPeek'
import { useRun } from '../hooks/useMigrationEvents'

interface Props {
  tree: TreeNode
  /** Latest status per file_path (relative to extraction root), from FileEvents. */
  fileStatus?: Map<string, string>
  /** Step 5 After-tree construction tags. Takes precedence over fileStatus dots. */
  buildTags?: Map<string, BuildTag>
  /** Dest currently being written/tested — auto-open ancestors and scroll to it. */
  focusPath?: string | null
  /** Namespace for the sessionStorage expand state — pass a distinct key per
   * tree instance so two trees on one page don't share expansion. */
  storageKey?: string
  /** Expand every directory on first render (until the user toggles). */
  defaultExpandAll?: boolean
  /** Click a file to open the peek modal. `source` reads intake bytes;
   * `proposal` shows a brief of what will be generated (nothing on disk). */
  inspect?: 'source' | 'proposal' | 'exploration-doc'
  mappings?: FileMapping[]
  /** Required when inspect="exploration-doc" */
  explorationRunId?: string
  /** When set, file clicks call this instead of opening a peek modal. */
  onFileInspect?: (path: string) => void
  selectedInspectPath?: string | null
}

const EMPTY_STATUS: Map<string, string> = new Map()

function allDirPaths(node: TreeNode, prefix: string, out: string[]): string[] {
  for (const c of node.children ?? []) {
    const path = prefix ? `${prefix}/${c.name}` : c.name
    if (c.type === 'dir') {
      out.push(path)
      allDirPaths(c, path, out)
    }
  }
  return out
}

function loadExpanded(storageKey: string, tree: TreeNode, defaultExpandAll: boolean): Set<string> {
  try {
    const raw = sessionStorage.getItem(storageKey)
    if (raw) return new Set(JSON.parse(raw) as string[])
  } catch {
    /* fall through to default */
  }
  return defaultExpandAll ? new Set(allDirPaths(tree, '', [])) : new Set()
}

function countFiles(node: TreeNode): number {
  if (node.type === 'file') return 1
  return (node.children ?? []).reduce((n, c) => n + countFiles(c), 0)
}

function dotClass(status: string | undefined, animate: boolean): string {
  if (!status) return 'status-dot'
  const s = status.toUpperCase()
  if (s === 'OK' || s === 'DONE' || s === 'PASSED' || s === 'TESTED') return 'status-dot ok'
  if (s === 'RUNNING' || s === 'IN-PROGRESS' || s === 'TESTING')
    return animate ? 'status-dot running' : 'status-dot'
  if (s === 'FAILED' || s === 'BLOCKED' || s === 'BUGFIX') return 'status-dot failed'
  return 'status-dot'
}

function Tag({ tag }: { tag: BuildTag; animate: boolean }) {
  return <span className={`tree-tag tree-tag-${tag}`}>{BUILD_TAG_LABEL[tag]}</span>
}

function FolderTag({
  todo,
  live,
  testing,
  done,
  bugfix,
  total,
  animate,
}: {
  todo: number
  live: number
  testing: number
  done: number
  bugfix: number
  total: number
  animate: boolean
}) {
  const written = done + bugfix
  if (live > 0 && animate) {
    return (
      <span className="tree-tag tree-tag-in-progress">
        {live} writing · {written}/{total}
      </span>
    )
  }
  if (testing > 0 && animate) {
    return (
      <span className="tree-tag tree-tag-testing">
        {testing} testing · {written}/{total}
      </span>
    )
  }
  if (bugfix > 0) {
    return (
      <span className="tree-tag tree-tag-bugfix">
        {bugfix} bugfix · {written}/{total}
      </span>
    )
  }
  if (done > 0) {
    return (
      <span className="tree-tag tree-tag-done">
        {done}/{total} done
      </span>
    )
  }
  if (todo > 0) {
    return (
      <span className="tree-tag tree-tag-pending">
        {todo} to do
      </span>
    )
  }
  return null
}

function folderMeterVisible(tally: ReturnType<typeof folderTally>, animate: boolean): boolean {
  if (tally.total === 0) return false
  const busy = animate ? tally.live + tally.testing : 0
  if (tally.todo === 0 && busy === 0 && tally.bugfix === 0) return false
  if (busy === 0 && tally.done === 0 && tally.bugfix === 0) return false
  return true
}

function FolderMeter({ tally, animate }: { tally: ReturnType<typeof folderTally>; animate: boolean }) {
  const { total, done, live, testing, bugfix, todo } = tally
  if (total === 0 || !folderMeterVisible(tally, animate)) return null
  const busy = animate ? live + testing : 0
  return (
    <span className={`folder-meter${busy > 0 ? ' live' : ''}`} aria-hidden>
      {done > 0 ? <span className="folder-meter-seg done" style={{ flexGrow: done }} /> : null}
      {bugfix > 0 ? <span className="folder-meter-seg bugfix" style={{ flexGrow: bugfix }} /> : null}
      {busy > 0 ? <span className="folder-meter-seg live" style={{ flexGrow: Math.max(busy, 1) }} /> : null}
      {todo > 0 ? <span className="folder-meter-seg rest" style={{ flexGrow: todo }} /> : null}
    </span>
  )
}

function ancestorDirs(path: string): string[] {
  const parts = path.split('/').filter(Boolean)
  const out: string[] = []
  for (let i = 1; i < parts.length; i++) out.push(parts.slice(0, i).join('/'))
  return out
}

export default function FileTree({
  tree,
  fileStatus = EMPTY_STATUS,
  buildTags,
  focusPath = null,
  storageKey = 'cobalt.tree.expanded',
  defaultExpandAll = false,
  inspect,
  mappings,
  explorationRunId,
  onFileInspect,
  selectedInspectPath,
}: Props) {
  const { live } = useRun()
  const animate = live
  const [expanded, setExpanded] = useState<Set<string>>(() =>
    loadExpanded(storageKey, tree, defaultExpandAll),
  )
  const [peekPath, setPeekPath] = useState<string | null>(null)
  const collapsedByUser = useRef(new Set<string>())

  useLayoutEffect(() => {
    if (!focusPath) return
    const el = document.querySelector(`[data-tree-path="${CSS.escape(focusPath)}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [focusPath])

  const toggle = useCallback(
    (path: string) => {
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(path)) {
          next.delete(path)
          collapsedByUser.current.add(path)
        } else {
          next.add(path)
          collapsedByUser.current.delete(path)
        }
        try {
          sessionStorage.setItem(storageKey, JSON.stringify([...next]))
        } catch {
          /* storage unavailable — expansion just won't persist */
        }
        return next
      })
    },
    [storageKey],
  )

  const liveAncestors = focusPath ? ancestorDirs(focusPath) : []
  const isDirOpen = (path: string) => {
    if (collapsedByUser.current.has(path)) return false
    if (expanded.has(path)) return true
    return liveAncestors.includes(path)
  }

  const renderNode = (node: TreeNode, path: string, depth: number) => {
    const indent = { paddingLeft: `${depth * 14 + 4}px` }
    if (node.type === 'dir') {
      const isOpen = isDirOpen(path)
      const nFiles = countFiles(node)
      const tally = buildTags ? folderTally(node, path, buildTags) : null
      const dirBusy = Boolean(animate && tally && (tally.live > 0 || tally.testing > 0))
      const dirBuilt = Boolean(
        tally && tally.done > 0 && tally.todo === 0 && tally.bugfix === 0 && !dirBusy,
      )
      const showMeter = tally ? folderMeterVisible(tally, animate) : false
      const meterIndent = { paddingLeft: `${depth * 14 + 4 + 26}px`, paddingRight: 8 }

      return (
        <div key={path} className="tree-dir-block">
          <button
            type="button"
            className={`tree-row dir${dirBusy ? ' building' : ''}${dirBuilt ? ' built' : ''}`}
            style={indent}
            onClick={() => toggle(path)}
            aria-expanded={isOpen}
            data-tree-path={path}
          >
            <ChevronIcon className={`chev ${isOpen ? 'open' : ''}`} width={12} height={12} />
            <FolderIcon width={13} height={13} />
            <span className="tree-name">{node.name}</span>
            <span className="count">
              {nFiles} file{nFiles === 1 ? '' : 's'}
            </span>
            {tally ? <FolderTag {...tally} animate={animate} /> : null}
          </button>
          {showMeter && tally ? (
            <div className="folder-meter-track" style={meterIndent}>
              <FolderMeter tally={tally} animate={animate} />
            </div>
          ) : null}
          {isOpen &&
            (node.children ?? []).map((c) =>
              renderNode(c, `${path}/${c.name}`, depth + 1),
            )}
        </div>
      )
    }
    const tag = buildTags?.get(path)
    const status = tag ?? fileStatus.get(path)
    const clickable = Boolean(inspect)
    const busy = animate && (tag === 'in-progress' || tag === 'testing')
    const settled = tag === 'done' || tag === 'tested'
    return (
      <button
        type="button"
        key={path}
        className={`tree-row file ${node.is_cobol ? 'cobol' : ''}${clickable ? ' clickable' : ''}${busy ? ' building' : ''}${settled ? ' built' : ''}${selectedInspectPath === path ? ' is-inspect-selected' : ''}`}
        style={indent}
        title={status ? `${path} — ${status}` : path}
        data-tree-path={path}
        onClick={clickable ? () => (onFileInspect ? onFileInspect(path) : setPeekPath(path)) : undefined}
      >
        <span className={dotClass(busy ? 'IN-PROGRESS' : typeof status === 'string' && !tag ? status : tag, animate)} />
        <FileIcon width={13} height={13} />
        <span className="tree-name">{node.name}</span>
        {tag ? <Tag tag={tag} animate={animate} /> : null}
      </button>
    )
  }

  // Root is the extraction dir itself — render its children at depth 0 so
  // file paths match the backend's relative paths (see intake._flatten).
  return (
    <div className="file-tree">
      {(tree.children ?? []).map((c) => renderNode(c, c.name, 0))}
      {peekPath && inspect === 'exploration-doc' && explorationRunId && !onFileInspect && (
        <ExplorationDocPeek runId={explorationRunId} path={peekPath} onClose={() => setPeekPath(null)} />
      )}
      {peekPath && inspect && inspect !== 'exploration-doc' && (
        <FilePeek
          key={peekPath}
          path={peekPath}
          mode={inspect}
          mappings={mappings}
          generated={
            buildTags?.get(peekPath) === 'done' ||
            buildTags?.get(peekPath) === 'tested' ||
            buildTags?.get(peekPath) === 'skipped'
          }
          onClose={() => setPeekPath(null)}
        />
      )}
    </div>
  )
}
