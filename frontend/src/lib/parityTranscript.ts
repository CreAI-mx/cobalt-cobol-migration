/** Parse parity sandbox stdout — structured when output matches known patterns, else line diff. */

export interface ParityTranscript {
  outcome: 'found' | 'not_found' | null
  name: string | null
  balance: string | null
}

export interface ParityFieldDiff {
  field: string
  label: string
  equal: boolean
  cobol: string
  csharp: string
  fix_hint?: string | null
  display_equal?: boolean
  numeric_equal?: boolean
}

export interface ParityComparison {
  output_equal: boolean
  display_equal: boolean
  mode?: 'structured' | 'lines'
  diffs: ParityFieldDiff[]
}

const MAX_LINE_ROWS = 40

export function normalizeStdout(text: string): string {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  return lines.map((l) => l.replace(/\s+$/, '')).join('\n').replace(/\n+$/, '')
}

export function meaningfulOutputLines(stdout: string): string[] {
  const norm = normalizeStdout(stdout)
  const lines = norm
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l && !l.startsWith('#') && !/^\$\s/.test(l))
  return lines.length > 0 ? lines : norm.trim() ? [norm.trim()] : []
}

export function parseParityTranscript(stdout: string): ParityTranscript {
  let outcome: ParityTranscript['outcome'] = null
  let name: string | null = null
  let balance: string | null = null

  for (const raw of stdout.split('\n')) {
    const line = raw.trim()
    if (/^ACCOUNT NOT FOUND\.?$/i.test(line)) outcome = 'not_found'
    if (/^ACCOUNT FOUND:?$/i.test(line)) outcome = 'found'
    const nm = line.match(/^NAME:\s*(.+)$/i)
    if (nm) name = nm[1].trim()
    const bal = line.match(/^BALANCE:\s*(.+)$/i)
    if (bal) balance = bal[1].trim()
  }

  return { outcome, name, balance }
}

export function outcomeLabel(t: ParityTranscript): string | null {
  if (t.outcome === 'found') return 'ACCOUNT FOUND'
  if (t.outcome === 'not_found') return 'ACCOUNT NOT FOUND'
  return null
}

function parseBalanceValue(raw: string | null): number | null {
  if (!raw) return null
  const s = raw.replace(/[+,$,\s]/g, '')
  if (!s) return null
  if (s.includes('.')) {
    const n = Number(s)
    return Number.isFinite(n) ? n : null
  }
  if (/^\d+$/.test(s) && s.length >= 3) return Number(s) / 100
  const n = Number(s)
  return Number.isFinite(n) ? n : null
}

export function formatOutputPreview(stdout: string, tx: ParityTranscript): string {
  if (tx.outcome === 'found') {
    const lines = ['ACCOUNT FOUND:']
    if (tx.name) lines.push(`NAME: ${tx.name}`)
    if (tx.balance) lines.push(`BALANCE: ${tx.balance}`)
    return lines.join('\n')
  }
  if (tx.outcome === 'not_found') return 'ACCOUNT NOT FOUND.'
  const lines = meaningfulOutputLines(stdout)
  if (lines.length > 0) return lines.slice(-12).join('\n')
  return '(no output)'
}

export function comparisonSimilarityPct(comparison: ParityComparison): number {
  if (comparison.diffs.length === 0) return 0
  const ok = comparison.diffs.filter((d) => d.equal).length
  return Math.round((ok / comparison.diffs.length) * 100)
}

export function compareParityTranscripts(cobol: ParityTranscript, csharp: ParityTranscript): ParityComparison | null {
  if (!cobol.outcome || !csharp.outcome) return null

  const outcomeEq = cobol.outcome === csharp.outcome
  const nameEq = (cobol.name ?? '').trim().toUpperCase() === (csharp.name ?? '').trim().toUpperCase()
  const cbVal = parseBalanceValue(cobol.balance)
  const csVal = parseBalanceValue(csharp.balance)
  const balanceDisplayEq = (cobol.balance ?? '') === (csharp.balance ?? '')
  const balanceValueEq = cbVal !== null && csVal !== null ? cbVal === csVal : balanceDisplayEq
  const balanceEq = balanceValueEq

  const diffs: ParityFieldDiff[] = [
    {
      field: 'outcome',
      label: 'Outcome (FOUND / NOT FOUND)',
      equal: outcomeEq,
      cobol: outcomeLabel(cobol) ?? '—',
      csharp: outcomeLabel(csharp) ?? '—',
      fix_hint: outcomeEq
        ? null
        : 'Fix migrated CLI behavior to match legacy COBOL for the same fixture input.',
    },
    {
      field: 'name',
      label: 'NAME',
      equal: nameEq,
      cobol: cobol.name ?? '—',
      csharp: csharp.name ?? '—',
      fix_hint: nameEq ? null : 'Check record layout, field width, and Trim when reading fixture data.',
    },
    {
      field: 'balance',
      label: 'BALANCE',
      equal: balanceEq,
      cobol: cobol.balance ?? '—',
      csharp: csharp.balance ?? '—',
      display_equal: balanceDisplayEq,
      numeric_equal: balanceValueEq,
      fix_hint: balanceEq
        ? null
        : !balanceValueEq && cbVal !== null && csVal !== null
          ? `Numeric value differs (~${cbVal} vs ~${csVal}). Review PIC and decimal parsing.`
          : 'Match DISPLAY/formatting in the migrated CLI to legacy COBOL output.',
    },
  ]

  const output_equal = outcomeEq && nameEq && balanceEq
  return {
    output_equal,
    display_equal: output_equal && balanceDisplayEq,
    mode: 'structured',
    diffs,
  }
}

export function compareStdoutLines(cobStdout: string, csStdout: string): ParityComparison {
  const cobNorm = normalizeStdout(cobStdout)
  const csNorm = normalizeStdout(csStdout)
  const output_equal = cobNorm === csNorm

  const cl = meaningfulOutputLines(cobStdout)
  const csl = meaningfulOutputLines(csStdout)
  const rowCount = Math.min(Math.max(cl.length, csl.length, 1), MAX_LINE_ROWS)
  const diffs: ParityFieldDiff[] = []

  for (let i = 0; i < rowCount; i++) {
    const cobol = i < cl.length ? cl[i] : '—'
    const csharp = i < csl.length ? csl[i] : '—'
    const equal = cobol === csharp
    diffs.push({
      field: `line-${i + 1}`,
      label: `Line ${i + 1}`,
      equal,
      cobol,
      csharp,
      fix_hint: equal ? null : 'Align migrated stdout with legacy COBOL for this line (DISPLAY/WRITE).',
    })
  }

  if (Math.max(cl.length, csl.length) > MAX_LINE_ROWS) {
    diffs.push({
      field: 'truncated',
      label: '…',
      equal: cl.length === csl.length,
      cobol: `${cl.length} line(s)`,
      csharp: `${csl.length} line(s)`,
      fix_hint: `Showing first ${MAX_LINE_ROWS} lines — compare full transcripts in the terminals.`,
    })
  }

  return {
    output_equal,
    display_equal: output_equal,
    mode: 'lines',
    diffs,
  }
}

/** Prefer structured field diff when stdout matches; otherwise normalized line diff. */
export function compareParityOutputs(cobStdout: string, csStdout: string): ParityComparison {
  const cobTx = parseParityTranscript(cobStdout)
  const csTx = parseParityTranscript(csStdout)
  const structured = compareParityTranscripts(cobTx, csTx)
  if (structured) return structured
  return compareStdoutLines(cobStdout, csStdout)
}

export function transcriptsAlign(cobol: ParityTranscript, csharp: ParityTranscript): boolean {
  return compareParityTranscripts(cobol, csharp)?.output_equal ?? false
}
