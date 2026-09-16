/** File peek modal. Origin: real intake bytes. Destination: brief of what
 * will be written — no fabricated source. Importers: FileTree.tsx.
 * API: GET /migration/{id}/file, GET /extracts. User: "necesito un modal
 * para que cuando le de click a un archivo se abra, en especial los de
 * origen; en el destino como una descripcion si agentica pero breve, no
 * construiremos aun nada de archivos." */
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { getExtracts, getGeneratedFile, getSourceFile } from '../lib/api'
import type { SourceFileView } from '../lib/api'
import { briefForProposed } from '../lib/proposedBrief'
import type { FileMapping } from '../lib/targetArchitecture'
import { useRun } from '../hooks/useMigrationEvents'
import { peekLanguage } from '../lib/peekLanguage'
import { SpinnerIcon, XIcon } from './Icons'

const CodePreview = lazy(() => import('./CodePreview'))

interface Props {
  path: string
  mode: 'source' | 'proposal'
  mappings?: FileMapping[]
  /** True when this proposal-tree node already has a real file on disk
   * (buildTag done/tested) — show the actual generated content instead of
   * the pre-generation brief. */
  generated?: boolean
  onClose: () => void
}

export default function FilePeek({ path, mode, mappings = [], generated = false, onClose }: Props) {
  const { runId } = useRun()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [source, setSource] = useState<SourceFileView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(mode === 'source' || generated)
  const [extractHint, setExtractHint] = useState<{
    suggested_component_name?: string | null
    business_rules?: unknown[]
  } | null>(null)

  useEffect(() => {
    const d = dialogRef.current
    if (!d) return
    if (!d.open) d.showModal()
    const onCancel = (e: Event) => {
      e.preventDefault()
      onClose()
    }
    d.addEventListener('cancel', onCancel)
    return () => d.removeEventListener('cancel', onCancel)
  }, [onClose])

  useEffect(() => {
    setSource(null)
    setExtractHint(null)
    const wantsRealFile = mode === 'source' || generated
    if (!wantsRealFile || !runId) {
      setLoading(false)
      setError(mode === 'source' && !runId ? 'No intake yet — nothing to open.' : null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    const fetcher = mode === 'source' ? getSourceFile : getGeneratedFile
    void fetcher(runId, path)
      .then((row) => {
        if (!cancelled) setSource(row)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [mode, path, runId, generated])

  useEffect(() => {
    if (mode !== 'proposal' || !runId) return
    const origin = mappings.find((m) => m.to === path)?.from
    if (!origin) return
    let cancelled = false
    void getExtracts(runId)
      .then((rows) => {
        if (cancelled) return
        const hit = rows.find((r) => r.path === origin)
        if (hit) {
          setExtractHint({
            suggested_component_name: hit.suggested_component_name,
            business_rules: hit.business_rules,
          })
        }
      })
      .catch(() => { /* extracts optional until Phase 2 finishes */ })
    return () => {
      cancelled = true
    }
  }, [mode, path, runId, mappings])

  const brief = mode === 'proposal' ? briefForProposed(path, mappings, extractHint) : null

  return (
    <dialog
      ref={dialogRef}
      className="file-peek"
      onClick={(e) => {
        if (e.target === dialogRef.current) onClose()
      }}
    >
      <div className="file-peek-panel">
        <header className="file-peek-head">
          <div>
            <p className="file-peek-kicker">
              {mode === 'source' ? 'Origin' : generated ? 'Generated · on disk' : 'Proposed · not on disk'}
              {source?.program_id ? ` · PROGRAM-ID ${source.program_id}` : ''}
              {source ? ` · ${source.kind}` : ''}
              {!generated && brief ? ` · ${brief.role}` : ''}
            </p>
            <h2 className="mono">{path}</h2>
            {brief?.origin && (
              <p className="muted file-peek-origin">from {brief.origin}</p>
            )}
          </div>
          <button type="button" className="file-peek-close" onClick={onClose} aria-label="Close">
            <XIcon width={16} height={16} />
          </button>
        </header>

        <div className="file-peek-body">
          {loading && (
            <p className="muted">
              <SpinnerIcon width={14} height={14} />{' '}
              {generated ? 'Reading generated file…' : 'Reading source…'}
            </p>
          )}
          {error && <p className="file-peek-error">{error}</p>}
          {(mode === 'source' || generated) && source?.binary && (
            <p className="muted">Binary file — not shown.</p>
          )}
          {(mode === 'source' || generated) && source && !source.binary && (
            <>
              {source.truncated && (
                <p className="muted">Preview truncated at 200 KB.</p>
              )}
              <Suspense
                fallback={
                  <pre className="file-peek-code-fallback">{source.content}</pre>
                }
              >
                <CodePreview
                  code={source.content}
                  language={peekLanguage(path, source.kind, generated)}
                />
              </Suspense>
            </>
          )}
          {mode === 'proposal' && !generated && brief && (
            <p className="file-peek-brief">{brief.body}</p>
          )}
        </div>
      </div>
    </dialog>
  )
}