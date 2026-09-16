/** HITL architecture workshop — Step 3. The human picks a C# shape, writes a
 * re-architecture directive, Recreate estate regenerates After/ontology trees,
 * Accept unlocks Phase 4. Importer: Step3Architecture.tsx. API:
 * POST/GET /migration/{id}/architecture. Schema: architecture_decisions.
 * User: "necesito un componente human in the loop que realmente participe
 * en la creacion y proponga re arquitectura, si es necesaria, re crear el estate." */
import { useEffect, useState } from 'react'
import { useRun } from '../hooks/useMigrationEvents'
import { phaseIsWaiting } from '../lib/estateBuild'
import { ARCH_SHAPES, type ArchShape } from '../lib/targetArchitecture'

export default function ArchitectureWorkshop() {
  const { architecture, submitArchitecture, previewArchitecture, phaseMap, proposal, live } = useRun()
  const [shape, setShape] = useState<ArchShape>(architecture.shape)
  const [directive, setDirective] = useState(architecture.directive)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setShape(architecture.shape)
    setDirective(architecture.directive)
  }, [architecture.shape, architecture.directive, architecture.revision])

  const phase4 = phaseMap.get('Phase 4')
  const waiting = phaseIsWaiting(phaseMap, 'Phase 4', architecture.action)
  const converting =
    live &&
    phase4 != null &&
    phase4.status === 'RUNNING' &&
    !waiting
  const alreadyDone = phase4?.status === 'OK' || phase4?.status === 'BLOCKED'

  const persist = async (action: 'recreated' | 'accepted') => {
    setBusy(true)
    try {
      await submitArchitecture({ shape, directive, action })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card arch-workshop">
      <div className="arch-workshop-head">
        <h2>Human in the loop</h2>
        {architecture.revision > 0 && (
          <span className="arch-rev">rev {String(architecture.revision).padStart(2, '0')}</span>
        )}
      </div>
      <p className="muted">
        You co-author the C# estate. Pick a shape, write how it should change,
        then Recreate to redraw After + ontology. Accept is what starts
        conversion (Phase 4). Phases 0–3 keep running in the background.
      </p>
      {(/\[doc-master:/i.test(architecture.directive) ||
        (proposal.comment && architecture.directive.includes(proposal.comment))) && (
        <p className="arch-wait" role="status">
          Corrections request applied to this tree
          {proposal.comment ? `: "${proposal.comment}"` : ''}.
          Accept architecture if After looks right, then approve on Corrections.
        </p>
      )}

      <fieldset className="arch-shapes" disabled={busy}>
        <legend className="sr-only">Target shape</legend>
        {ARCH_SHAPES.map((opt) => (
          <label
            key={opt.id}
            className={`arch-shape${shape === opt.id ? ' selected' : ''}`}
          >
            <input
              type="radio"
              name="arch-shape"
              value={opt.id}
              checked={shape === opt.id}
              onChange={() => {
                setShape(opt.id)
                previewArchitecture({ shape: opt.id })
              }}
            />
            <strong>{opt.label}</strong>
            <span>{opt.blurb}</span>
          </label>
        ))}
      </fieldset>

      <label className="arch-directive-label" htmlFor="arch-directive">
        Re-architecture directive
      </label>
      <textarea
        id="arch-directive"
        className="arch-directive"
        value={directive}
        onChange={(e) => setDirective(e.target.value)}
        placeholder="e.g. Keep posting and reversal in one use case; isolate ledger writes behind a port; do not split COBOL folders 1:1."
        disabled={busy}
      />

      {(converting && architecture.action === 'accepted') && (
        <p className="arch-wait" role="status">
          Phase 4 is converting this accepted estate. Recreate pauses remaining
          files until you Accept again — they take the new shape. Files already
          written keep the previous accept.
        </p>
      )}
      {converting && architecture.action === 'recreated' && (
        <p className="arch-wait" role="status">
          Recreate is stored. The current wave finishes, then Phase 4 waits here
          for Accept — remaining files and documentation use this estate.
        </p>
      )}
      {alreadyDone && (
        <p className="arch-warn" role="status">
          Phase 4 already {phase4?.status}. Recreate still updates this proposal;
          conversion for this run has finished, so a new Accept applies on the
          next run.
        </p>
      )}
      {waiting && architecture.action !== 'accepted' && (
        <p className="arch-wait" role="status">
          Pipeline is waiting here — Accept architecture to start or resume C#
          generation with this estate.
        </p>
      )}
      {architecture.action === 'accepted' && !converting && !alreadyDone && (
        <p className="arch-ok" role="status">
          Accepted {architecture.shape}
          {architecture.directive ? ` — ${architecture.directive.slice(0, 80)}` : ''}.
          Phase 4 may start as soon as Phases 0–3 finish.
        </p>
      )}

      <div className="arch-workshop-actions">
        <button
          type="button"
          className="btn"
          disabled={busy}
          onClick={() => void persist('recreated')}
        >
          Recreate estate
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={busy || (architecture.action === 'accepted' && shape === architecture.shape && directive === architecture.directive)}
          onClick={() => void persist('accepted')}
        >
          Accept architecture
        </button>
      </div>
    </div>
  )
}
