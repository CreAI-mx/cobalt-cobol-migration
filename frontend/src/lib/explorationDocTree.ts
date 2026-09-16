import type { TreeNode } from './api'

/** Build a FileTree-compatible tree from flat doc paths (folders appear as created). */
export function explorationDocTree(paths: string[]): TreeNode {
  const root: TreeNode = { name: 'docs', type: 'dir', children: [], is_cobol: false }
  const sorted = [...paths]
    .filter((p) => p && p !== 'documentation_graph.json')
    .sort((a, b) => a.localeCompare(b))
  for (const rel of sorted) {
    const parts = rel.split('/')
    let cur = root
    let prefix = ''
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]
      const isFile = i === parts.length - 1
      prefix = prefix ? `${prefix}/${name}` : name
      cur.children = cur.children ?? []
      let child = cur.children.find((c) => c.name === name)
      if (!child) {
        child = {
          name,
          type: isFile ? 'file' : 'dir',
          children: isFile ? undefined : [],
          is_cobol: false,
        }
        cur.children.push(child)
      }
      if (!isFile) cur = child
    }
  }
  return root
}

export function explorationDocFileStatus(paths: string[], liveDocPhase: boolean): Map<string, string> {
  const m = new Map<string, string>()
  const files = paths.filter((p) => p && p !== 'documentation_graph.json')
  files.forEach((p, i) => {
    if (liveDocPhase && i === files.length - 1) m.set(p, 'RUNNING')
    else m.set(p, 'OK')
  })
  return m
}
