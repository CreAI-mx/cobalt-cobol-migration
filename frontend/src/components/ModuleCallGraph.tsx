/** Interactive CALL subgraph — hero visual for Step 2. Pan (drag), zoom (wheel), click node → source. */
import { useCallback, useMemo, useRef, useState } from 'react'
import type { ExplorationModule, ExplorationPack } from '../lib/api'

function programLabel(mod: ExplorationModule, path: string, fallback: string): string {
  const i = mod.member_paths.indexOf(path)
  if (i >= 0 && mod.source_program_ids[i]) return mod.source_program_ids[i]
  return fallback
}

type Edge = ExplorationPack['call_graph_resolved']['edges'][number]

type NodeModel = {
  path: string
  programId: string
  file: string
  x: number
  y: number
}

function layoutNodes(paths: string[], edges: Edge[]): NodeModel[] {
  const localEdges = edges.filter((e) => paths.includes(e.from_path) && paths.includes(e.to_path))
  const incoming = new Map<string, number>()
  for (const p of paths) incoming.set(p, 0)
  for (const e of localEdges) {
    incoming.set(e.to_path, (incoming.get(e.to_path) ?? 0) + 1)
  }
  const order: string[] = []
  const q = paths.filter((p) => (incoming.get(p) ?? 0) === 0).sort()
  const rem = new Map(incoming)
  while (q.length) {
    const p = q.shift()!
    order.push(p)
    for (const e of localEdges.filter((x) => x.from_path === p)) {
      const n = (rem.get(e.to_path) ?? 1) - 1
      rem.set(e.to_path, n)
      if (n === 0) q.push(e.to_path)
    }
  }
  for (const p of paths.sort()) {
    if (!order.includes(p)) order.push(p)
  }
  const cols = order.length || 1
  return order.map((path, i) => {
    const file = path.split('/').pop() ?? path
    const programId = file.replace(/\.(cob|cbl|cpy)$/i, '')
    return {
      path,
      programId,
      file,
      x: 80 + i * (cols > 3 ? 200 : 240),
      y: 120 + (i % 2) * 40,
    }
  })
}

export default function ModuleCallGraph({
  mod,
  edges,
  onSelectPath,
}: {
  mod: ExplorationModule
  edges: Edge[]
  onSelectPath?: (path: string) => void
}) {
  const paths = useMemo(() => [...mod.member_paths].sort(), [mod.member_paths])
  const localEdges = useMemo(
    () => edges.filter((e) => paths.includes(e.from_path) && paths.includes(e.to_path)),
    [edges, paths],
  )
  const nodes = useMemo(() => layoutNodes(paths, localEdges), [paths, localEdges])
  const byPath = useMemo(() => new Map(nodes.map((n) => [n.path, n])), [nodes])
  const width = Math.max(520, nodes.length * 220)
  const height = 280

  const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 })
  const [hover, setHover] = useState<string | null>(null)
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null)

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const delta = e.deltaY > 0 ? 0.92 : 1.08
    setTransform((t) => ({ ...t, k: Math.min(2.5, Math.max(0.45, t.k * delta)) }))
  }, [])

  const onPointerDown = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('.graph-node')) return
    drag.current = { px: e.clientX, py: e.clientY, x: transform.x, y: transform.y }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return
    setTransform((t) => ({
      ...t,
      x: drag.current!.x + (e.clientX - drag.current!.px),
      y: drag.current!.y + (e.clientY - drag.current!.py),
    }))
  }

  const onPointerUp = () => {
    drag.current = null
  }

  return (
    <div
        className="module-detail-visual__call"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <svg
          className="graph-hero-svg"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label="CALL graph"
          style={{
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})`,
            transformOrigin: 'center center',
          }}
        >
          <defs>
            <marker id="call-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#8b5cf6" />
            </marker>
          </defs>
          {localEdges.map((e) => {
            const a = byPath.get(e.from_path)
            const b = byPath.get(e.to_path)
            if (!a || !b) return null
            return (
              <g key={`${e.from_path}-${e.to_path}`}>
                <line
                  x1={a.x + 90}
                  y1={a.y + 28}
                  x2={b.x + 10}
                  y2={b.y + 28}
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  markerEnd="url(#call-arrow)"
                />
                <text x={(a.x + b.x) / 2 + 50} y={(a.y + b.y) / 2 + 22} className="graph-edge-label" fontSize={11}>
                  CALL
                </text>
              </g>
            )
          })}
          {nodes.map((n) => {
            const isEntry = n.path === mod.entrypoint_path
            const hot = hover === n.path
            return (
              <g
                key={n.path}
                className="graph-node"
                transform={`translate(${n.x}, ${n.y})`}
                onMouseEnter={() => setHover(n.path)}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelectPath?.(n.path)}
                style={{ cursor: onSelectPath ? 'pointer' : 'default' }}
              >
                <rect
                  width={180}
                  height={56}
                  rx={10}
                  fill={hot ? '#312e81' : '#1e293b'}
                  stroke={isEntry ? '#22c55e' : hot ? '#a78bfa' : '#475569'}
                  strokeWidth={isEntry ? 2.5 : 1.5}
                />
                <text x={12} y={22} fill="#f8fafc" fontSize={13} fontWeight={600}>
                  {programLabel(mod, n.path, n.programId)}
                </text>
                <text x={12} y={40} fill="#94a3b8" fontSize={11} fontFamily="JetBrains Mono, monospace">
                  {n.file}
                </text>
                {isEntry && (
                  <text x={12} y={52} fill="#22c55e" fontSize={9} fontWeight={600}>
                    ENTRY
                  </text>
                )}
              </g>
            )
          })}
        </svg>
    </div>
  )
}
