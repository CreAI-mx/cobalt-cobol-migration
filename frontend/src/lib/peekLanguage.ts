/** Maps file path + API kind to Prism language id for FilePeek. Importer: FilePeek.tsx.
 * No API/schema. User: resaltar colores en lenguaje de destino (C# / COBOL). */
export function peekLanguage(path: string, kind: string | undefined, generated: boolean): string {
  const lower = path.toLowerCase()
  if (lower.endsWith('.cs')) return 'csharp'
  if (generated && (lower.endsWith('.csproj') || lower.endsWith('.sln'))) return 'markup'
  if (kind === 'cobol_source' || kind === 'copybook') return 'cobol'
  if (/\.(cbl|cob|cpy)$/.test(lower)) return 'cobol'
  if (lower.endsWith('.md')) return 'markdown'
  if (lower.endsWith('.csproj') || lower.endsWith('.xml')) return 'markup'
  return 'csharp'
}
