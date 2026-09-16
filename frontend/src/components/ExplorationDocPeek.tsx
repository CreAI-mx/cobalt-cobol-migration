import { useEffect, useRef, useState } from 'react'
import { explorationDocumentUrl } from '../lib/api'
import ExplorationDocPreview from './ExplorationDocPreview'
import { SpinnerIcon, XIcon } from './Icons'

export default function ExplorationDocPeek({
  runId,
  path,
  onClose,
}: {
  runId: string
  path: string
  onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    dialogRef.current?.showModal()
  }, [])

  useEffect(() => {
    setText(null)
    setError(null)
    void fetch(explorationDocumentUrl(runId, path))
      .then(async (res) => {
        if (!res.ok) throw new Error(`${res.status}`)
        return res.text()
      })
      .then(setText)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [runId, path])

  return (
    <dialog ref={dialogRef} className="file-peek-dialog" onClose={onClose}>
      <div className="file-peek-head">
        <span className="mono">{path}</span>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <XIcon width={16} height={16} />
        </button>
      </div>
      <div className="file-peek-body exploration-doc-peek-body">
        {error && <p className="explore-error">{error}</p>}
        {!text && !error && <SpinnerIcon width={20} height={20} />}
        {text && <ExplorationDocPreview path={path} text={text} />}
      </div>
    </dialog>
  )
}
