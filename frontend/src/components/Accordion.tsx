/** Minimal disclosure section — closed by default (minimalism pass 2026-09-15:
 * detail panels collapse behind one-line summaries; only primary content stays
 * visible). Native <details> keeps it keyboard-accessible for free.
 * Importer: Step3Architecture.tsx. Optional `n` numbers the "what happens" sequence.
 * User: number the accordions so the flow is structured. */
import type { ReactNode } from 'react'

interface Props {
  n?: number
  title: string
  hint?: string
  children: ReactNode
}

export default function Accordion({ n, title, hint, children }: Props) {
  const num = n != null ? String(n).padStart(2, '0') : null
  return (
    <details className="accordion">
      <summary>
        {num && <span className="accordion-n">{num}</span>}
        <span className="accordion-title">{title}</span>
        {hint && <span className="accordion-hint">{hint}</span>}
      </summary>
      <div className="accordion-body">{children}</div>
    </details>
  )
}
