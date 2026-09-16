import { useEffect, useMemo, useState } from 'react'
import type { ExplorationPack, TreeNode } from '../lib/api'
import { explorationDocumentUrl, explorationDocsZipUrl, getExplorationDocsManifest } from '../lib/api'
import { explorationDocFileStatus, explorationDocTree } from '../lib/explorationDocTree'
import FileTree from './FileTree'
import ExplorationDocPreview from './ExplorationDocPreview'
import { SpinnerIcon } from './Icons'

function flattenFiles(node: TreeNode, prefix = ''): string[] {
  const out: string[] = []
  for (const c of node.children ?? []) {
    const p = prefix ? `${prefix}/${c.name}` : c.name
    if (c.type === 'file') out.push(p)
    else out.push(...flattenFiles(c, p))
  }
  return out
}

export default function DocumentationArchitecture({
  pack,
  docPhaseLive,
  layout = 'full',
}: {
  pack: ExplorationPack
  docPhaseLive?: boolean
  layout?: 'rail' | 'full'
}) {
  const documentation = pack.documentation
  const [diskManifest, setDiskManifest] = useState<Awaited<ReturnType<typeof getExplorationDocsManifest>>>(null)

  useEffect(() => {
    let cancelled = false
    void getExplorationDocsManifest(pack.run_id).then((m) => {
      if (!cancelled) setDiskManifest(m)
    })
    return () => {
      cancelled = true
    }
  }, [pack.run_id])

  const docPaths = useMemo(() => {
    const fromPack = (documentation?.documents ?? []).filter((p) => p && p !== 'documentation_graph.json')
    const fromDisk = (diskManifest?.documents ?? []).filter((p) => p && p !== 'documentation_graph.json')
    const merged = fromPack.length >= fromDisk.length ? fromPack : fromDisk
    return merged.length > 0 ? merged : fromDisk.length > 0 ? fromDisk : fromPack
  }, [documentation?.documents, diskManifest?.documents])

  const docTree = useMemo(() => explorationDocTree(docPaths), [docPaths])
  const docFileStatus = useMemo(
    () => explorationDocFileStatus(docPaths, Boolean(docPhaseLive)),
    [docPaths, docPhaseLive],
  )
  const fileCount = docPaths.length
  const hasFiles = fileCount > 0
  const agentStatus = documentation?.agent_status ?? diskManifest?.agent_status
  const corpus = documentation?.corpus ?? diskManifest?.corpus
  const corpusHint =
    corpus && (corpus.files_copied > 0 || corpus.archive_members_expanded > 0)
      ? ` · corpus: ${corpus.files_copied} repo files, ${corpus.archive_members_expanded} from ZIPs`
      : ''
  const zipReady = hasFiles || Boolean(diskManifest?.documents?.length)

  const [selected, setSelected] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  useEffect(() => {
    if (selected && docPaths.includes(selected)) return
    const flat = flattenFiles(docTree)
    const pick = flat.find((p) => p.endsWith('.md')) ?? flat[0] ?? null
    setSelected(pick)
  }, [docTree, docPaths, selected])

  useEffect(() => {
    if (layout !== 'full' || !selected) {
      setPreview(null)
      setPreviewError(null)
      return
    }
    let cancelled = false
    setPreviewLoading(true)
    setPreviewError(null)
    void fetch(explorationDocumentUrl(pack.run_id, selected))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.text()
      })
      .then((text) => {
        if (!cancelled) {
          setPreview(text)
          setPreviewLoading(false)
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setPreviewError(e instanceof Error ? e.message : String(e))
          setPreview(null)
          setPreviewLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [pack.run_id, selected, layout])

  const head = (
    <header className="explore-docs-head">
      <div>
        <p className="eyebrow">AS-IS documentation</p>
        <h3>Architecture deliverables</h3>
        <p className="muted explore-docs-lede">
          {hasFiles
            ? `${fileCount} deliverables${corpusHint} · full-repo snapshot for agents`
            : docPhaseLive
              ? 'Generating deliverables…'
              : documentation
                ? 'Skeleton pending — re-run exploration if empty'
                : 'Run exploration through Documentation phase'}
        </p>
      </div>
      <div className="explore-docs-head-actions">
        {agentStatus ? (
          <span className="chip explore-docs-status">{agentStatus}</span>
        ) : null}
        <span className="mono muted">
          {(documentation?.corpus ?? diskManifest?.corpus)?.files_copied ?? 0} files · $
          {(documentation?.cost_usd ?? 0).toFixed(4)} ·{' '}
          {((documentation?.input_tokens ?? 0) + (documentation?.output_tokens ?? 0)).toLocaleString()} tok
        </span>
        {zipReady ? (
          <a className="btn primary" href={explorationDocsZipUrl(pack.run_id)}>
            Download all (.zip)
          </a>
        ) : (
          <button type="button" className="btn" disabled>
            Download all (.zip)
          </button>
        )}
      </div>
    </header>
  )

  const treeBody = hasFiles ? (
    <FileTree
      tree={docTree}
      fileStatus={docFileStatus}
      storageKey={`cobalt.tree.explore.docs.${pack.run_id}`}
      defaultExpandAll
      inspect="exploration-doc"
      explorationRunId={pack.run_id}
      onFileInspect={layout === 'full' ? setSelected : undefined}
      selectedInspectPath={layout === 'full' ? selected : undefined}
    />
  ) : (
    <div className="explore-docs-empty">
      {docPhaseLive ? (
        <>
          <SpinnerIcon width={22} height={22} />
          <p>Agents are writing the AS-IS dossier…</p>
        </>
      ) : (
        <p className="muted">
          No deliverables found for this run yet. If files exist under{' '}
          <code className="mono">migration-state/runs/{pack.run_id}/docs-cobol-accounting-system/docs</code>, reload
          the page or restart the API.
        </p>
      )}
    </div>
  )

  if (layout === 'rail') {
    return (
      <div className="explore-docs-rail">
        {head}
        <div className="explore-docs-rail-tree tree-panel">{treeBody}</div>
      </div>
    )
  }

  return (
    <section className="card explore-docs-panel explore-docs-panel--full">
      {head}
      <div className="explore-docs-split">
        <aside className="explore-docs-tree tree-panel">
          <p className="explore-docs-tree-label mono muted">Deliverables tree</p>
          {treeBody}
        </aside>
        <article className="explore-docs-preview">
          {selected ? <header className="explore-docs-preview-head mono">{selected}</header> : null}
          <div className="explore-docs-preview-body">
            {!selected && hasFiles && <p className="muted">Select a file in the tree.</p>}
            {selected && previewLoading && !preview && !previewError && <SpinnerIcon width={20} height={20} />}
            {previewError && <p className="explore-error">{previewError}</p>}
            {preview && selected && <ExplorationDocPreview path={selected} text={preview} />}
            {!hasFiles && (
              <p className="muted explore-docs-preview-placeholder">
                Preview will appear here when markdown files are available.
              </p>
            )}
          </div>
        </article>
      </div>
    </section>
  )
}
