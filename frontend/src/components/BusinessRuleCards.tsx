/** Business rules in module dossier — grouped by source file, anchor as action. */
import { useState } from 'react'
import type { ExplorationModule } from '../lib/api'

export type BusinessRule = ExplorationModule['business_rules'][number]

function groupRules(rules: BusinessRule[]): Map<string, BusinessRule[]> {
  const m = new Map<string, BusinessRule[]>()
  for (const r of rules) {
    const anchor = r.anchors[0] ?? ''
    const file = anchor.includes(':') ? anchor.split(':')[0] : '(unknown)'
    const list = m.get(file) ?? []
    list.push(r)
    m.set(file, list)
  }
  return m
}

function ruleKind(rule: BusinessRule): { label: string; tone: 'draft' | 'agent' | 'human' } {
  const src = rule.source ?? 'deterministic_draft'
  if (src === 'human') return { label: 'Confirmed', tone: 'human' }
  if (src === 'agent' || src.includes('llm')) return { label: 'Agent', tone: 'agent' }
  return { label: 'Draft', tone: 'draft' }
}

function displayTitle(rule: BusinessRule): string {
  const anchor = rule.anchors[0] ?? ''
  if (rule.id.startsWith('BR-CALL-')) {
    const call = rule.id.replace('BR-CALL-', '')
    return `External call · ${call}`
  }
  if (anchor.includes(':')) {
    const para = anchor.split(':').slice(1).join(':')
    if (para.startsWith('CALL')) return rule.text
    return `Paragraph · ${para}`
  }
  return rule.text.length > 120 ? `${rule.text.slice(0, 117)}…` : rule.text
}

export default function BusinessRuleCards({
  rules,
  limit = 12,
  onOpenAnchor,
}: {
  rules: BusinessRule[]
  limit?: number
  onOpenAnchor?: (path: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const visible = expanded ? rules : rules.slice(0, limit)
  const grouped = groupRules(visible)

  if (rules.length === 0) {
    return <p className="muted">No rules yet — run exploration or wait for agentic extraction.</p>
  }

  return (
    <div className="rule-cards">
      {[...grouped.entries()].map(([file, fileRules]) => (
        <section key={file} className="rule-file-group">
          <h6 className="rule-file-heading mono">{file}</h6>
          <ul className="rule-card-list">
            {fileRules.map((r) => {
              const kind = ruleKind(r)
              const anchor = r.anchors[0] ?? ''
              const path = anchor.includes(':') ? anchor.split(':')[0] : ''
              return (
                <li key={r.id} className={`rule-card rule-card--${kind.tone}`}>
                  <div className="rule-card-head">
                    <span className="rule-card-id mono">{r.id}</span>
                    <span className={`rule-card-badge rule-card-badge--${kind.tone}`}>{kind.label}</span>
                  </div>
                  <p className="rule-card-text">{displayTitle(r)}</p>
                  {kind.tone === 'draft' && (
                    <p className="rule-card-hint muted">{r.text}</p>
                  )}
                  {anchor && (
                    <button
                      type="button"
                      className="rule-card-anchor mono"
                      onClick={() => path && onOpenAnchor?.(path)}
                      disabled={!path || !onOpenAnchor}
                    >
                      {anchor}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
      {rules.length > limit && (
        <button type="button" className="btn small rule-expand" onClick={() => setExpanded((v) => !v)}>
          {expanded ? 'Show fewer' : `Show all ${rules.length} rules`}
        </button>
      )}
    </div>
  )
}
