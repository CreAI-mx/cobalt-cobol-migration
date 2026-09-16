/** One pseudocode flowchart — never a CALL graph plus a paragraph graph. */
import { useMemo } from 'react'
import type { ExplorationPack, ExplorationProgram, FlowEdge, FlowNode } from '../lib/api'
import { SparkIcon, SpinnerIcon } from './Icons'

const FLOW_KINDS = new Set(['start', 'process', 'decision', 'loop', 'call', 'end', 'merge'])
const COL_X = 200
const BOX_W = 300
const BOX_H = 52
const STEP_Y = 88

type Placed = FlowNode & { x: number; y: number; cx: number; cy: number }

function asFlow(nodes: { id: string; label: string; kind: string; seq?: number }[], edges: FlowEdge[]): { nodes: FlowNode[]; edges: FlowEdge[] } | null {
  if (!nodes.length || !nodes.every((n) => FLOW_KINDS.has(n.kind))) return null
  return {
    nodes: nodes.map((n, i) => ({
      id: n.id,
      label: n.label,
      kind: n.kind as FlowNode['kind'],
      seq: n.seq ?? i,
    })),
    edges,
  }
}

function place(nodes: FlowNode[]): Placed[] {
  return [...nodes]
    .sort((a, b) => a.seq - b.seq)
    .map((n, i) => {
      const y = 28 + i * STEP_Y
      return { ...n, x: COL_X - BOX_W / 2, y, cx: COL_X, cy: y + BOX_H / 2 }
    })
}

function NodeShape({ node }: { node: Placed }) {
  const { x, y, kind, label } = node
  if (kind === 'merge') {
    return <circle cx={node.cx} cy={node.cy} r={6} className="flow-merge" />
  }
  if (kind === 'decision' || kind === 'loop') {
    const cx = node.cx
    const cy = node.cy
    const w = BOX_W / 2
    const h = BOX_H / 2 + 4
    return (
      <>
        <polygon
          points={`${cx},${cy - h} ${cx + w},${cy} ${cx},${cy + h} ${cx - w},${cy}`}
          className={kind === 'loop' ? 'flow-loop' : 'flow-decision'}
        />
        <text x={cx} y={cy + 4} textAnchor="middle" className="flow-label">
          {label.slice(0, 34)}
        </text>
      </>
    )
  }
  const rx = kind === 'start' || kind === 'end' ? 26 : 8
  return (
    <>
      <rect x={x} y={y} width={BOX_W} height={BOX_H} rx={rx} className={`flow-box is-${kind}`} />
      <text x={node.cx} y={node.cy + 4} textAnchor="middle" className="flow-label">
        {label.slice(0, 42)}
      </text>
    </>
  )
}

function mergeFlows(programs: ExplorationProgram[]): { nodes: FlowNode[]; edges: FlowEdge[]; pathOf: Record<string, string> } {
  const nodes: FlowNode[] = []
  const edges: FlowEdge[] = []
  const pathOf: Record<string, string> = {}
  let seq = 0
  for (const [index, prog] of programs.entries()) {
    const local = prog.flow_nodes ?? []
    if (!local.length) continue
    const remap = new Map(local.map((n) => [n.id, `${index}:${n.id}`]))
    for (const n of local) {
      const id = remap.get(n.id)!
      pathOf[id] = prog.path
      nodes.push({
        ...n,
        id,
        seq: seq++,
        label: n.kind === 'start' ? (prog.program_id ?? n.label) : n.label,
      })
    }
    for (const e of prog.flow_edges ?? []) {
      const source = remap.get(e.source)
      const target = remap.get(e.target)
      if (source && target) edges.push({ ...e, source, target })
    }
  }
  return { nodes, edges, pathOf }
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
  const programs = pack.programs ?? []
  const agentFlow = useMemo(() => {
    const g = pack.relation_graph
    if (g?.generated_by !== 'agent' || !g.nodes?.length) return null
    return asFlow(
      g.nodes.map((n) => ({ id: n.id, label: n.label, kind: n.kind, seq: n.seq })),
      g.edges,
    )
  }, [pack.relation_graph])

  const merged = useMemo(() => mergeFlows(programs), [programs])
  const flow = agentFlow
  const pathOf = merged.pathOf

  if (graphLive && !flow) {
    return (
      <div className="estate-graph estate-graph--pending">
        <SpinnerIcon width={22} height={22} />
        <p>Agent writing the pseudocode flow…</p>
      </div>
    )
  }

  if (!flow) {
    return (
      <div className="estate-graph estate-graph--pending">
        <SparkIcon width={22} height={22} />
        <p className="estate-graph-pending-title">Pseudocode flow</p>
        <p className="muted">The origin flowchart is drawn from PROCEDURE logic (IF, PERFORM, loops, CALL) — not from files. A monolith in one script still explodes into steps.</p>
      </div>
    )
  }

  const placed = place(flow.nodes)
  const byId = new Map(placed.map((n) => [n.id, n]))
  const height = Math.max(420, 48 + placed.length * STEP_Y)
  const width = 560
  const source = agentFlow ? 'agent' : 'COBOL'

  return (
    <div className="estate-graph">
      <div className="estate-graph-toolbar">
        <span className="estate-graph-title">Pseudocode flow</span>
        <span className="chip explore-docs-status">{source}</span>
        <span className="mono muted">
          origin flow · {flow.nodes.length} steps
        </span>
      </div>
      <div className="estate-graph-viewport estate-graph-viewport--flow">
        <svg
          className="estate-graph-svg"
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="xMidYMin meet"
          role="img"
          aria-label="Pseudocode flow"
        >
          <defs>
            <marker id="flow-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#94a3b8" />
            </marker>
            <marker id="flow-loop-head" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="#fb7185" />
            </marker>
          </defs>
          {flow.edges.map((edge, i) => {
            const a = byId.get(edge.source)
            const b = byId.get(edge.target)
            if (!a || !b) return null
            const back = b.seq <= a.seq || edge.kind === 'loop' || edge.kind === 'exit'
            const no = edge.kind === 'no'
            const x1 = no ? a.cx + BOX_W / 2 : a.cx
            const y1 = no ? a.cy : a.y + BOX_H
            const y2 = b.y
            const d = back
              ? `M ${a.cx - BOX_W / 2} ${a.cy} C ${a.cx - 130} ${a.cy}, ${b.cx - 130} ${b.cy}, ${b.cx - BOX_W / 2} ${b.cy}`
              : no
                ? `M ${x1} ${a.cy} L ${a.cx + 168} ${a.cy} L ${a.cx + 168} ${b.cy} L ${b.cx + BOX_W / 2} ${b.cy}`
                : `M ${a.cx} ${y1} L ${b.cx} ${y2}`
            const cls =
              back || edge.kind === 'loop' || edge.kind === 'exit'
                ? 'flow-edge is-loop'
                : edge.kind === 'yes'
                  ? 'flow-edge is-yes'
                  : edge.kind === 'no'
                    ? 'flow-edge is-no'
                    : 'flow-edge'
            const midY = back ? (a.cy + b.cy) / 2 : (y1 + y2) / 2
            const midX = back ? a.cx - 118 : no ? a.cx + 176 : a.cx + 10
            return (
              <g key={`${edge.source}-${edge.target}-${i}`}>
                <path
                  d={d}
                  className={cls}
                  fill="none"
                  markerEnd={back ? 'url(#flow-loop-head)' : 'url(#flow-head)'}
                />
                {edge.label || edge.kind === 'yes' || edge.kind === 'no' ? (
                  <text x={midX} y={midY} className="flow-edge-label">
                    {edge.label || edge.kind}
                  </text>
                ) : null}
              </g>
            )
          })}
          {placed.map((node) => (
            <g
              key={node.id}
              className="estate-node"
              style={{ cursor: pathOf[node.id] ? 'pointer' : 'default' }}
              onClick={() => pathOf[node.id] && onSelectProgram?.(pathOf[node.id])}
            >
              <NodeShape node={node} />
            </g>
          ))}
        </svg>
      </div>
    </div>
  )
}
