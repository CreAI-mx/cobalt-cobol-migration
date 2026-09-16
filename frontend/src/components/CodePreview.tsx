/** Read-only syntax highlight for FilePeek — C# destination, COBOL origin.
 * Importer: FilePeek.tsx only. No API/schema change; highlights SourceFileView.content.
 * User (verbatim): "que resalte colores de fucnioens palabras etcetc, en este caso
 * el lengaujede destino" */
import type { CSSProperties } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'

const cobaltPrism: Record<string, CSSProperties> = {
  'code[class*="language-"]': {
    fontFamily: 'var(--font-mono)',
    fontSize: '12px',
    lineHeight: 1.55,
    tabSize: 2,
  },
  comment: { color: '#64748b', fontStyle: 'italic' },
  prolog: { color: '#64748b' },
  doctype: { color: '#64748b' },
  punctuation: { color: '#475569' },
  property: { color: '#0f172a' },
  tag: { color: '#0369a1' },
  boolean: { color: '#b45309' },
  number: { color: '#b45309' },
  constant: { color: '#b45309' },
  symbol: { color: '#b45309' },
  deleted: { color: '#dc2626' },
  selector: { color: '#047857' },
  'attr-name': { color: '#047857' },
  string: { color: '#047857' },
  char: { color: '#047857' },
  builtin: { color: '#6d28d9' },
  inserted: { color: '#047857' },
  operator: { color: '#475569' },
  entity: { color: '#0f172a' },
  url: { color: '#0369a1' },
  variable: { color: '#0f172a' },
  atrule: { color: '#0369a1' },
  'attr-value': { color: '#047857' },
  function: { color: '#6d28d9', fontWeight: 600 },
  'class-name': { color: '#0f172a', fontWeight: 600 },
  keyword: { color: '#0369a1', fontWeight: 600 },
  regex: { color: '#047857' },
  important: { color: '#dc2626', fontWeight: 600 },
}

interface Props {
  code: string
  language: string
}

export default function CodePreview({ code, language }: Props) {
  return (
    <div className="file-peek-code-wrap">
      <SyntaxHighlighter
        language={language}
        style={cobaltPrism}
        customStyle={{
          margin: 0,
          padding: '12px 14px',
          background: '#f8fafc',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
        }}
        showLineNumbers
        lineNumberStyle={{ color: '#94a3b8', minWidth: '2.5em', paddingRight: '1em' }}
        wrapLongLines
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}
