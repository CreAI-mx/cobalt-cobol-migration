/** Agentic relation+sequence graph — never a flowchart of the origin scripts. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { ExplorationPack, FlowEdge, RelationGraphNode } from '../lib/api'
import { SparkIcon, SpinnerIcon } from './Icons'

const KINDS = new Set(['program', 'paragraph', 'data', 'external', 'decision', 'loop', 'call', 'start', 'end', 'process', 'merge'])
const COL_W = 196
const BOX_W = 240
const BOX_H = 52
const ROW_H = 92
const FLOW_COL = 292
const MIN_ZOOM = 0.35
const MAX_ZOOM = 2.4
const LEGEND = [
  { kind: 'start', label: 'start/end' },
  { kind: 'process', label: 'process' },
  { kind: 'decision', label: 'decision' },
  { kind: 'loop', label: 'loop' },
  { kind: 'call', label: 'subroutine' },
  { kind: 'data', label: 'data' },
]

type FlowGraph = { schema: number; generated_by: string; nodes: RelationGraphNode[]; edges: FlowEdge[] }
type Placed = RelationGraphNode & { x: number; y: number; cx: number; cy: number }

function stem(path: string): string {
  const file = path.split('/').pop() ?? path
  return file.replace(/\.(cob|cbl|cpy)$/i, '')
}

function fromCallPack(pack: ExplorationPack): FlowGraph | null {
  const programs = pack.programs ?? []
  if (!programs.length) return null
  const entries = new Set((pack.modules ?? []).map((m) => m.entrypoint_path).filter(Boolean) as string[])
  const nodes: RelationGraphNode[] = programs.map((p, i) => ({
    id: `pgm:${(p.program_id || stem(p.path)).toUpperCase()}`,
    label: p.program_id || stem(p.path),
    kind: entries.has(p.path) || i === 0 ? 'start' : 'program',
    rank: 0,
    seq: i,
    path: p.path,
    evidence: [p.path],
  }))
  const byPath = new Map(programs.map((p, i) => [p.path, nodes[i].id]))
  const edges: FlowEdge[] = []
  for (const e of pack.call_graph_resolved?.edges ?? []) {
    const source = byPath.get(e.from_path)
    const target = byPath.get(e.to_path)
    if (source && target) edges.push({ source, target, kind: 'call', label: 'CALL' })
  }
  return { schema: 2, generated_by: 'call-graph', nodes, edges }
}

function clamp(n: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, n))
}

function pathOfNode(n: RelationGraphNode): string | undefined {
  if (n.path) return n.path
  const ev = n.evidence?.[0]
  if (!ev) return undefined
  return ev.replace(/:\d+$/, '')
}

function layeredPlace(nodes: RelationGraphNode[], edges: FlowEdge[]): Placed[] {
  const ids = new Set(nodes.map((n) => n.id))
  const incoming = new Map<string, number>()
  const outs = new Map<string, string[]>()
  for (const n of nodes) incoming.set(n.id, 0)
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue
    incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1)
    const list = outs.get(e.source) ?? []
    list.push(e.target)
    outs.set(e.source, list)
  }
  const rankOf = new Map<string, number>()
  for (const n of nodes) {
    if (typeof n.rank === 'number' && n.rank > 0) rankOf.set(n.id, n.rank)
  }
  const roots = nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0)
  const start = roots.length ? roots : nodes.slice(0, 1)
  const q: string[] = []
  for (const n of start) {
    if (!rankOf.has(n.id)) rankOf.set(n.id, 0)
    q.push(n.id)
  }
  for (let i = 0; i < q.length; i++) {
    const id = q[i]
    const r = rankOf.get(id) ?? 0
    for (const t of outs.get(id) ?? []) {
      const next = r + 1
      if (!rankOf.has(t) || next > (rankOf.get(t) ?? 0)) {
        rankOf.set(t, Math.max(rankOf.get(t) ?? 0, next))
        q.push(t)
      }
    }
  }
  for (const n of nodes) {
    if (!rankOf.has(n.id)) rankOf.set(n.id, n.rank ?? 0)
  }
  const byRank = new Map<number, RelationGraphNode[]>()
  for (const n of nodes) {
    const r = rankOf.get(n.id) ?? 0
    const list = byRank.get(r) ?? []
    list.push(n)
    byRank.set(r, list)
  }
  for (const list of byRank.values()) {
    list.sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0) || a.label.localeCompare(b.label))
  }
  const placed: Placed[] = []
  for (const r of [...byRank.keys()].sort((a, b) => a - b)) {
    const list = byRank.get(r) ?? []
    list.forEach((n, i) => {
      const x = 28 + r * COL_W
      const y = 28 + i * ROW_H
      placed.push({ ...n, rank: r, x, y, cx: x + BOX_W / 2, cy: y + BOX_H / 2 })
    })
  }
  return placed
}

function isFlowGraph(nodes: RelationGraphNode[]): boolean {
  return nodes.some((n) => n.kind === 'decision' || n.kind === 'loop' || n.kind === 'process' || n.kind === 'call')
}

function withFlowOrigin(graph: FlowGraph): FlowGraph {
  const starts = graph.nodes.filter((n) => n.kind === 'start' && n.id !== 'origin')
  if (starts.length < 2 || graph.nodes.some((n) => n.id === 'origin')) return graph
  return {
    ...graph,
    nodes: [{ id: 'origin', label: 'Origin', kind: 'start', rank: 0, seq: -1, evidence: [] }, ...graph.nodes],
    edges: [...starts.map((s) => ({ source: 'origin', target: s.id, kind: 'next' })), ...graph.edges],
  }
}

function columnIndex(nodes: RelationGraphNode[], edges: FlowEdge[]): Map<string, number> {
  const col = new Map<string, number>()
  const numbered = nodes.filter((n) => n.id !== 'origin' && /^\d+:/.test(n.id))
  if (numbered.length >= Math.max(2, Math.floor(nodes.length / 2))) {
    for (const n of nodes) {
      if (n.id === 'origin') continue
      const m = /^(\d+):/.exec(n.id)
      col.set(n.id, m ? Number(m[1]) : 0)
    }
    return col
  }
  const ids = new Set(nodes.map((n) => n.id))
  const outs = new Map<string, string[]>()
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue
    const list = outs.get(e.source) ?? []
    list.push(e.target)
    outs.set(e.source, list)
  }
  const starts = nodes.filter((n) => n.kind === 'start' && n.id !== 'origin')
  starts.forEach((s, i) => {
    const q = [s.id]
    col.set(s.id, i)
    for (let qi = 0; qi < q.length; qi++) {
      for (const t of outs.get(q[qi]) ?? []) {
        if (!col.has(t)) {
          col.set(t, i)
          q.push(t)
        }
      }
    }
  })
  let extra = Math.max(starts.length, 1)
  for (const n of nodes) {
    if (n.id === 'origin') continue
    if (!col.has(n.id)) col.set(n.id, extra++)
  }
  return col
}

function topoColumn(nodes: RelationGraphNode[], edges: FlowEdge[]): RelationGraphNode[] {
  const ids = new Set(nodes.map((n) => n.id))
  const incoming = new Map<string, number>()
  const outs = new Map<string, string[]>()
  for (const n of nodes) incoming.set(n.id, 0)
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target) || e.source === e.target) continue
    incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1)
    const list = outs.get(e.source) ?? []
    list.push(e.target)
    outs.set(e.source, list)
  }
  const starts = nodes.filter((n) => n.kind === 'start')
  const q = (starts.length ? starts : nodes.filter((n) => (incoming.get(n.id) ?? 0) === 0)).map((n) => n.id)
  const seen = new Set<string>()
  const ordered: RelationGraphNode[] = []
  const byId = new Map(nodes.map((n) => [n.id, n]))
  for (let i = 0; i < q.length; i++) {
    const id = q[i]
    if (seen.has(id)) continue
    seen.add(id)
    const node = byId.get(id)
    if (node) ordered.push(node)
    for (const t of outs.get(id) ?? []) {
      if (!seen.has(t)) q.push(t)
    }
  }
  for (const n of nodes) {
    if (!seen.has(n.id)) ordered.push(n)
  }
  const body = ordered.filter((n) => n.kind !== 'end')
  const ends = ordered.filter((n) => n.kind === 'end')
  return [...body, ...ends]
}

function flowchartPlace(nodes: RelationGraphNode[], edges: FlowEdge[]): Placed[] {
  const colOf = columnIndex(nodes, edges)
  const cols = new Map<number, RelationGraphNode[]>()
  for (const n of nodes) {
    if (n.id === 'origin') continue
    const c = colOf.get(n.id) ?? 0
    const list = cols.get(c) ?? []
    list.push(n)
    cols.set(c, list)
  }
  const colIds = [...cols.keys()].sort((a, b) => a - b)
  const placed: Placed[] = []
  const origin = nodes.find((n) => n.id === 'origin')
  const nCols = Math.max(1, colIds.length)
  if (origin) {
    const cx = 36 + ((nCols - 1) * FLOW_COL) / 2 + BOX_W / 2
    placed.push({ ...origin, x: cx - BOX_W / 2, y: 12, cx, cy: 12 + BOX_H / 2 })
  }
  colIds.forEach((c, gi) => {
    const list = topoColumn(cols.get(c) ?? [], edges)
    let y = origin ? 118 : 28
    list.forEach((n) => {
      const pad = n.kind === 'decision' || n.kind === 'loop' ? 18 : 0
      y += pad
      const x = 36 + gi * FLOW_COL
      placed.push({ ...n, x, y, cx: x + BOX_W / 2, cy: y + BOX_H / 2 })
      y += ROW_H + pad
    })
  })
  return placed
}

function NodeShape({ node }: { node: Placed }) {
  const { x, y, kind, label } = node
  const title = [label, node.evidence?.[0]].filter(Boolean).join(' · ')
  const caption = (
    <>
      <title>{title}</title>
      <text x={node.cx} y={node.cy + 4} textAnchor="middle" className="flow-label">
        {label.slice(0, 32)}
      </text>
    </>
  )
  if (kind === 'decision') {
    const w = BOX_W / 2 + 8
    const h = BOX_H / 2 + 14
    return (
      <>
        <polygon
          points={`${node.cx},${node.cy - h} ${node.cx + w},${node.cy} ${node.cx},${node.cy + h} ${node.cx - w},${node.cy}`}
          className="flow-decision"
        />
        {caption}
      </>
    )
  }
  if (kind === 'loop') {
    const w = BOX_W / 2
    const h = BOX_H / 2 + 8
    const cut = 18
    return (
      <>
        <polygon
          points={`${node.cx - w + cut},${node.cy - h} ${node.cx + w - cut},${node.cy - h} ${node.cx + w},${node.cy} ${node.cx + w - cut},${node.cy + h} ${node.cx - w + cut},${node.cy + h} ${node.cx - w},${node.cy}`}
          className="flow-loop"
        />
        {caption}
      </>
    )
  }
  if (kind === 'process') {
    const s = 18
    return (
      <>
        <polygon
          points={`${x + s},${y} ${x + BOX_W},${y} ${x + BOX_W - s},${y + BOX_H} ${x},${y + BOX_H}`}
          className="flow-process"
        />
        {caption}
      </>
    )
  }
  if (kind === 'data') {
    const ry = 9
    return (
      <>
        <path
          d={`M ${x} ${y + ry} L ${x} ${y + BOX_H - ry} A ${BOX_W / 2} ${ry} 0 0 0 ${x + BOX_W} ${y + BOX_H - ry} L ${x + BOX_W} ${y + ry}`}
          className="flow-data"
        />
        <ellipse cx={node.cx} cy={y + ry} rx={BOX_W / 2} ry={ry} className="flow-data" />
        {caption}
      </>
    )
  }
  if (kind === 'call' || kind === 'paragraph') {
    return (
      <>
        <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={6} className={`flow-box is-${kind === 'paragraph' ? 'paragraph' : 'call'}`} />
        <line x1={x + 10} y1={y + 6} x2={x + 10} y2={y + BOX_H - 6} className="flow-call-bar" />
        <line x1={x + BOX_W - 10} y1={y + 6} x2={x + BOX_W - 10} y2={y + BOX_H - 6} className="flow-call-bar" />
        {caption}
      </>
    )
  }
  if (kind === 'merge') {
    return (
      <>
        <circle cx={node.cx} cy={node.cy} r={16} className="flow-merge" />
        {caption}
      </>
    )
  }
  const rx = kind === 'start' || kind === 'end' ? 26 : 8
  return (
    <>
      <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={rx} className={`flow-box is-${kind}`} />
      {caption}
    </>
  )
}

export default function RepositoryLandscape({
  pack,
  onSelectProgram,
  graphLive,
}: {
  pack: ExplorationPack
  onSelectProgram?: (path: string) => void
  graphLive?: boolean
}) {
  const graph = useMemo(() => {
    const g = pack.relation_graph
    if (g?.nodes?.length && g.nodes.every((n) => KINDS.has(n.kind))) {
      if (g.generated_by === 'agent' || isFlowGraph(g.nodes)) {
        return withFlowOrigin({ schema: g.schema ?? 2, generated_by: g.generated_by ?? 'agent', nodes: g.nodes, edges: g.edges })
      }
    }
    return fromCallPack(pack)
  }, [pack])

  const pathOf = useMemo(() => {
    const m: Record<string, string> = {}
    for (const n of graph?.nodes ?? []) {
      const p = pathOfNode(n)
      if (p) m[n.id] = p
    }
    return m
  }, [graph])

  const asFlow = Boolean(graph && isFlowGraph(graph.nodes))
  const placed = useMemo(
    () => (graph ? (asFlow ? flowchartPlace(graph.nodes, graph.edges) : layeredPlace(graph.nodes, graph.edges)) : []),
    [graph, asFlow],
  )

  const width = useMemo(() => {
    if (!placed.length) return 640
    return Math.max(640, ...placed.map((n) => n.x + BOX_W + 40))
  }, [placed])
  const height = useMemo(() => {
    if (!placed.length) return 420
    return Math.max(420, ...placed.map((n) => n.y + BOX_H + 48))
  }, [placed])

  const viewportRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [tx, setTx] = useState(24)
  const [ty, setTy] = useState(16)
  const view = useRef({ scale: 1, tx: 24, ty: 16 })
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const panned = useRef(false)

  const commit = (s: number, x: number, y: number) => {
    view.current = { scale: s, tx: x, ty: y }
    setScale(s)
    setTx(x)
    setTy(y)
  }

  const applyZoom = (next: number, cx: number, cy: number) => {
    const prev = view.current
    const s = clamp(next, MIN_ZOOM, MAX_ZOOM)
    commit(s, cx - ((cx - prev.tx) / prev.scale) * s, cy - ((cy - prev.ty) / prev.scale) * s)
  }

  const fitWidth = () => {
    const el = viewportRef.current
    if (!el) return
    const sx = (el.clientWidth - 36) / width
    const sy = (el.clientHeight - 28) / height
    const s = clamp(Math.min(sx, sy), MIN_ZOOM, MAX_ZOOM)
    commit(s, (el.clientWidth - width * s) / 2, (el.clientHeight - height * s) / 2)
  }

  useLayoutEffect(() => {
    fitWidth()
  }, [width, height])

  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      applyZoom(view.current.scale * (e.deltaY > 0 ? 0.9 : 1.11), e.clientX - rect.left, e.clientY - rect.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [graph])

  if (graphLive && !graph) {
    return (
      <div className="estate-graph estate-graph--pending">
        <SpinnerIcon width={22} height={22} />
        <p>Agent reconstructing the estate graph…</p>
      </div>
    )
  }

  if (!graph) {
    return (
      <div className="estate-graph estate-graph--pending">
        <SparkIcon width={22} height={22} />
        <p className="estate-graph-pending-title">Agentic estate graph</p>
        <p className="muted">Run exploration to map CALL relations between programs. Color is node kind, not file. The agent may later enrich this graph.</p>
      </div>
    )
  }

  const byId = new Map(placed.map((n) => [n.id, n]))
  const pct = Math.round(scale * 100)

  return (
    <div className="estate-graph">
      <div className="estate-graph-toolbar">
        <span className="estate-graph-title">Pseudocode flow</span>
        <span className="chip explore-docs-status">{graph.generated_by === 'agent' ? 'agent' : asFlow ? 'flow' : 'CALL'}</span>
        <span className="mono muted">{graph.nodes.length} nodes · {graph.edges.length} edges</span>
        <div className="estate-zoom" role="group" aria-label="Zoom">
          <button type="button" className="estate-zoom-btn" onClick={() => applyZoom(view.current.scale * 0.85, (viewportRef.current?.clientWidth ?? 400) / 2, 120)} aria-label="Zoom out">−</button>
          <span className="estate-zoom-pct mono">{pct}%</span>
          <button type="button" className="estate-zoom-btn" onClick={() => applyZoom(view.current.scale * 1.18, (viewportRef.current?.clientWidth ?? 400) / 2, 120)} aria-label="Zoom in">+</button>
          <button type="button" className="estate-zoom-btn" onClick={fitWidth}>Fit</button>
        </div>
      </div>
      <div className="estate-graph-legend">
        {LEGEND.map((item) => (
          <span key={item.kind} className="estate-legend-item">
            <span className={`estate-legend-swatch flow-box is-${item.kind}`} />
            {item.label}
          </span>
        ))}
      </div>
      <div
        ref={viewportRef}
        className="estate-graph-viewport estate-graph-viewport--flow"
        onPointerDown={(e) => {
          if (e.button !== 0) return
          ;(e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId)
          panned.current = false
          drag.current = { x: e.clientX, y: e.clientY, tx: view.current.tx, ty: view.current.ty }
        }}
        onPointerMove={(e) => {
          const d = drag.current
          if (!d) return
          const dx = e.clientX - d.x
          const dy = e.clientY - d.y
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) panned.current = true
          commit(view.current.scale, d.tx + dx, d.ty + dy)
        }}
        onPointerUp={() => {
          drag.current = null
        }}
        onPointerCancel={() => {
          drag.current = null
        }}
      >
        <svg
          className="estate-graph-svg estate-graph-svg--zoom"
          width={width}
          height={height}
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="xMinYMin meet"
          role="img"
          aria-label="Pseudocode flow"
          style={{ transform: `translate(${tx}px, ${ty}px) scale(${scale})` }}
        >
          <defs>
            <marker id="flow-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" />
            </marker>
            <marker id="flow-loop-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#fb7185" />
            </marker>
          </defs>
          {graph.edges.map((edge, i) => {
            const a = byId.get(edge.source)
            const b = byId.get(edge.target)
            if (!a || !b) return null
            const back = b.cy + 8 < a.cy || edge.kind === 'loop' || edge.kind === 'exit'
            const no = edge.kind === 'no'
            const yes = edge.kind === 'yes'
            const split = Math.abs(a.cx - b.cx) > 48
            const midX = no ? a.cx + BOX_W / 2 + 36 : yes ? a.cx - 18 : (a.cx + b.cx) / 2
            const midY = (a.cy + b.cy) / 2
            const d = back
              ? `M ${a.cx - BOX_W / 2} ${a.cy} C ${a.cx - 120} ${a.cy}, ${b.cx - 120} ${b.cy}, ${b.cx - BOX_W / 2} ${b.cy}`
              : no
                ? `M ${a.cx + BOX_W / 2} ${a.cy} L ${a.cx + BOX_W / 2 + 48} ${a.cy} L ${a.cx + BOX_W / 2 + 48} ${b.cy} L ${b.cx + BOX_W / 2} ${b.cy}`
                : split
                  ? `M ${a.cx} ${a.y + BOX_H} C ${a.cx} ${a.cy + 50}, ${b.cx} ${b.cy - 50}, ${b.cx} ${b.y}`
                  : `M ${a.cx} ${a.y + BOX_H} L ${b.cx} ${b.y}`
            const cls =
              edge.kind === 'loop' || edge.kind === 'call' || edge.kind === 'perform'
                ? edge.kind === 'loop'
                  ? 'flow-edge is-loop'
                  : 'flow-edge is-call'
                : edge.kind === 'yes'
                  ? 'flow-edge is-yes'
                  : edge.kind === 'no'
                    ? 'flow-edge is-no'
                    : 'flow-edge'
            return (
              <g key={`${edge.source}-${edge.target}-${i}`}>
                <path d={d} className={cls} fill="none" markerEnd={back ? 'url(#flow-loop-head)' : 'url(#flow-head)'} />
                {edge.kind && edge.kind !== 'next' ? (
                  <text x={midX} y={midY - 4} className="flow-edge-label">{edge.label || edge.kind}</text>
                ) : null}
              </g>
            )
          })}
          {placed.map((node) => (
            <g
              key={node.id}
              className="estate-node"
              style={{ cursor: pathOf[node.id] ? 'pointer' : 'default' }}
              onClick={() => {
                if (panned.current) return
                const p = pathOf[node.id]
                if (p) onSelectProgram?.(p)
              }}
            >
              <NodeShape node={node} />
            </g>
          ))}
        </svg>
      </div>
    </div>
  )
}
