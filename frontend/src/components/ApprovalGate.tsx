/** ApprovalGate — Step 4 (Corrections). Real HITL: approve or request changes
 * before Migrate & Test unlocks. Decision is posted to POST /migration/{id}/gate.
 *
 * Redesigned twice per user feedback:
 * 1. ("no tiene sentido como regresar") — the persisted decision history
 *    (gate_decisions table, real, append-only) is always visible. A change
 *    request never silently disappears when the reviewer revisits.
 * 2. ("yo tengo que hacer yo el presionar el back... genera un modal donde se
 *    muestre el cambio") — applying a correction no longer force-navigates the
 *    reviewer to Architecture. It shows a modal, INLINE, with the concrete
 *    diff (e.g. the doc-master rename) and Approve / Request-more actions
 *    right there — no manual back-and-forth between steps. */
import { useEffect, useState } from 'react'
import { useRun } from '../hooks/useMigrationEvents'
import { getGateHistory } from '../lib/api'
import type { GateHistoryEntry } from '../lib/api'
import { docMasterName, mergeCorrectionDirective } from '../lib/targetArchitecture'
import { CheckIcon, XIcon } from './Icons'

interface Props {
  onApproved: () => void
  onApplyChanges: () => void
}

interface ChangeDiff {
  request: string
  oldMaster: string
  newMaster: string
  oldDirective: string
  newDirective: string
}

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const mins = Math.round(diffMs / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.round(mins / 60)
  return `${hrs}h ago`
}

function HistoryList({ history }: { history: GateHistoryEntry[] }) {
  if (history.length === 0) return null
  return (
    <div className="gate-history">
      <h3 className="gate-history-title">Decision history (persisted, real)</h3>
      <ul>
        {history.map((h, i) => (
          <li key={i} className={`gate-history-row gate-history-${h.decision}`}>
            <span className="gate-history-tag">
              {h.decision === 'approved' && 'APPROVED'}
              {h.decision === 'rejected' && 'USER REQUEST'}
              {h.decision === 'pending' && 'REOPENED'}
            </span>
            {h.comment && <span className="gate-history-comment">"{h.comment}"</span>}
            <span className="gate-history-time">{relativeTime(h.created_at)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The change-diff modal: shows EXACTLY what the applied request changed,
 * colored (destructive = old, ok = new), before asking for the next decision. */
function ChangeModal({
  diff, applying, onApprove, onRequestMore, onClose,
}: {
  diff: ChangeDiff
  applying: boolean
  onApprove: () => void
  onRequestMore: () => void
  onClose: () => void
}) {
  const renamed = diff.oldMaster !== diff.newMaster
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal-panel change-diff-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="change-modal-title">Applied to Architecture</h2>
        <p className="mono muted gate-current-request">
          <strong>Your request:</strong> "{diff.request}"
        </p>

        {renamed ? (
          <div className="diff-row" aria-label="File renamed">
            <span className="diff-old">docs/{diff.oldMaster}</span>
            <span className="diff-arrow">→</span>
            <span className="diff-new">docs/{diff.newMaster}</span>
          </div>
        ) : (
          <div className="diff-row diff-row-text">
            <span className="diff-new">+ {diff.request}</span>
          </div>
        )}

        <p className="muted">
          This is a proposal-level change — Phase 4 has not run yet with it, so
          nothing on disk is renamed until you approve and Migrate executes.
        </p>

        <div className="step-actions">
          <button type="button" className="btn primary" disabled={applying} onClick={onApprove}>
            <CheckIcon width={13} height={13} /> Approve &amp; continue to Migrate
          </button>
          <button type="button" className="btn" disabled={applying} onClick={onRequestMore}>
            Request more changes
          </button>
          <button type="button" className="btn btn-ghost" disabled={applying} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default function ApprovalGate({ onApproved, onApplyChanges: _onApplyChanges }: Props) {
  const { gateStatus, proposal, decideProposal, runId, architecture, submitArchitecture } = useRun()
  const [comment, setComment] = useState('')
  const [requesting, setRequesting] = useState(false)
  const [history, setHistory] = useState<GateHistoryEntry[]>([])
  const [applying, setApplying] = useState(false)
  const [changeModal, setChangeModal] = useState<ChangeDiff | null>(null)

  useEffect(() => {
    if (!runId) return
    getGateHistory(runId).then(setHistory).catch(() => { /* history is best-effort */ })
  }, [runId, gateStatus, proposal.decision])

  const lastRejection = [...history].reverse().find((h) => h.decision === 'rejected')
  const approved = proposal.decision === 'approved'
  const rejected = proposal.decision === 'changes_requested'

  const applyToArchitecture = async (text: string) => {
    const request = text.trim()
    if (!request) return
    setApplying(true)
    try {
      const oldDirective = architecture.directive
      const oldMaster = docMasterName(oldDirective)
      await decideProposal('changes_requested', request)
      const newDirective = mergeCorrectionDirective(oldDirective, request)
      await submitArchitecture({ shape: architecture.shape, directive: newDirective, action: 'recreated' })
      // Reopen the gate (client state) so a subsequent Approve isn't blocked by
      // the stale 'changes_requested' card — the modal now owns the next step.
      await decideProposal('pending', request)
      setComment(request)
      setRequesting(false)
      setChangeModal({
        request, oldMaster, newMaster: docMasterName(newDirective),
        oldDirective, newDirective,
      })
    } finally {
      setApplying(false)
    }
  }

  const approveAndContinue = async () => {
    // Two separate HITL tables: gate_decisions (this card) and
    // architecture_decisions (Phase 4's actual wait condition). Approving
    // here must satisfy BOTH — Phase 4 polls architecture_decisions.action
    // == 'accepted' and waits forever otherwise, regardless of gate_status.
    await submitArchitecture({
      shape: architecture.shape,
      directive: architecture.directive,
      action: 'accepted',
    })
    await decideProposal('approved', '')
    onApproved()
  }

  if (changeModal) {
    return (
      <>
        <ChangeModal
          diff={changeModal}
          applying={applying}
          onApprove={() => { setChangeModal(null); void approveAndContinue() }}
          onRequestMore={() => { setChangeModal(null); setRequesting(true) }}
          onClose={() => setChangeModal(null)}
        />
        <div className="card gate-card">
          <h2>Approve the proposed architecture</h2>
          <p className="muted">Change applied — close the dialog above or choose an action there.</p>
          <HistoryList history={history} />
        </div>
      </>
    )
  }

  if (approved) {
    return (
      <div className="card gate-card">
        <div className="decision-row">
          <span className="verdict passed">
            <CheckIcon width={11} height={11} /> APPROVED
          </span>
          <span className="muted">Stored on the run — real, persisted decision.</span>
        </div>
        <div className="step-actions">
          <button type="button" className="btn primary" onClick={onApproved}>
            Continue: Migrate &amp; Test →
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => { setComment(proposal.comment); void decideProposal('pending', proposal.comment) }}
          >
            Revisit decision
          </button>
        </div>
        <HistoryList history={history} />
      </div>
    )
  }

  if (rejected) {
    return (
      <div className="card gate-card">
        <div className="decision-row">
          <span className="verdict failed">
            <XIcon width={11} height={11} /> CHANGES REQUESTED
          </span>
        </div>
        {proposal.comment && (
          <p className="mono muted gate-current-request">
            <strong>User request:</strong> "{proposal.comment}"
          </p>
        )}
        <p className="muted">
          The request is stored, but it is not applied until Architecture
          recreates the estate. Migrate stays locked until you approve after that.
        </p>
        <div className="step-actions">
          <button
            type="button"
            className="btn primary"
            disabled={applying || !proposal.comment}
            onClick={() => void applyToArchitecture(proposal.comment)}
          >
            {applying ? 'Applying…' : 'Apply on Architecture'}
          </button>
          <button
            type="button"
            className="btn"
            disabled={applying}
            onClick={() => void decideProposal('pending', proposal.comment)}
          >
            Revisit decision
          </button>
        </div>
        <HistoryList history={history} />
      </div>
    )
  }

  return (
    <div className="card gate-card">
      <h2>Approve the proposed architecture</h2>
      <p className="muted">
        Review the before / after in Architecture. Phase 4+ generates C# following
        this shape. An explicit decision is required — the wizard never advances
        past this gate on its own.
      </p>
      {lastRejection && (
        <p className="mono muted gate-current-request">
          <strong>Previous user request</strong> ({relativeTime(lastRejection.created_at)}):
          "{lastRejection.comment}" — still unaddressed until you approve.
        </p>
      )}
      {requesting && (
        <textarea
          className="comment-box"
          aria-label="What should change in the proposal?"
          placeholder="What should change in the proposal?"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={3}
        />
      )}
      <div className="step-actions">
        {!requesting ? (
          <>
            <button type="button" className="btn primary" onClick={() => void approveAndContinue()}>
              <CheckIcon width={13} height={13} /> Approve &amp; continue to Migrate
            </button>
            <button type="button" className="btn" onClick={() => setRequesting(true)}>
              Request changes
            </button>
            {lastRejection?.comment && (
              <button
                type="button"
                className="btn"
                disabled={applying}
                onClick={() => void applyToArchitecture(lastRejection.comment)}
              >
                {applying ? 'Applying…' : 'Apply previous request on Architecture'}
              </button>
            )}
          </>
        ) : (
          <>
            <button
              type="button"
              className="btn primary"
              disabled={comment.trim().length === 0 || applying}
              onClick={() => void applyToArchitecture(comment)}
            >
              {applying ? 'Applying…' : 'Submit & apply on Architecture'}
            </button>
            <button type="button" className="btn" onClick={() => setRequesting(false)}>
              Cancel
            </button>
          </>
        )}
      </div>
      <HistoryList history={history} />
    </div>
  )
}
