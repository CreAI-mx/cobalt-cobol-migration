/** Parse ACCOUNT LOOKUP console transcripts from parity sandbox stdout. */

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
  diffs: ParityFieldDiff[]
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

/** Client-side comparison when API omits comparison (single-side runs). */
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
      label: 'Resultado',
      equal: outcomeEq,
      cobol: outcomeLabel(cobol) ?? '—',
      csharp: outcomeLabel(csharp) ?? '—',
      fix_hint: outcomeEq
        ? null
        : 'Corregir lógica de búsqueda en Handler/CLI C# vs COBOL READ/PERFORM.',
    },
    {
      field: 'name',
      label: 'NAME',
      equal: nameEq,
      cobol: cobol.name ?? '—',
      csharp: csharp.name ?? '—',
      fix_hint: nameEq ? null : 'Revisar ancho de nombre (30) y Trim en lectura de accounts.dat.',
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
          ? `Valor numérico distinto (~${cbVal} vs ~${csVal}). Revisar PIC y parseo decimal.`
          : 'Formatear BALANCE en Program.cs como DISPLAY COBOL (+0000010.00).',
    },
  ]

  const output_equal = outcomeEq && nameEq && balanceEq
  return {
    output_equal,
    display_equal: output_equal && balanceDisplayEq,
    diffs,
  }
}

export function transcriptsAlign(cobol: ParityTranscript, csharp: ParityTranscript): boolean {
  return compareParityTranscripts(cobol, csharp)?.output_equal ?? false
}
