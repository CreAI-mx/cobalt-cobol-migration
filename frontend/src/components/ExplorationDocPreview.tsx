/** AS-IS deliverable preview — same highlighted viewer as FilePeek (markdown, CSV, JSON). */
import { Suspense, lazy } from 'react'
import { docDeliverableLanguage } from '../lib/peekLanguage'

const CodePreview = lazy(() => import('./CodePreview'))

export default function ExplorationDocPreview({ path, text }: { path: string; text: string }) {
  const language = docDeliverableLanguage(path)
  return (
    <Suspense fallback={<pre className="exploration-doc-preview">{text}</pre>}>
      <CodePreview code={text} language={language} />
    </Suspense>
  )
}
