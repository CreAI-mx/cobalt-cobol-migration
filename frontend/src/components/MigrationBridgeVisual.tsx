/** COBOL module → planned C# shape (visual only, from exploration pack). */
import type { ExplorationModule } from '../lib/api'

function shortProject(path: string): string {
  const parts = path.replace(/\/$/, '').split('/')
  return parts[parts.length - 1] || path
}

export default function MigrationBridgeVisual({ mod }: { mod: ExplorationModule }) {
  const targets = [...new Set(mod.suggested_target_projects ?? [])].slice(0, 8)
  const w = Math.max(480, 120 + targets.length * 140)
  const h = 140
  return (
    <div className="module-detail-visual__bridge" aria-label="Migration target map">
      <svg className="bridge-svg" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="COBOL to C# targets">
        <rect x={16} y={36} width={140} height={68} rx={10} fill="#1e293b" stroke="#6366f1" strokeWidth={2} />
        <text x={86} y={58} fill="#e0e7ff" fontSize={12} fontWeight={600} textAnchor="middle">
          COBOL
        </text>
        <text x={86} y={78} fill="#94a3b8" fontSize={10} textAnchor="middle" fontFamily="JetBrains Mono, monospace">
          {mod.member_paths.length} pgms
        </text>
        <line x1={156} y1={70} x2={200} y2={70} stroke="#22c55e" strokeWidth={2} markerEnd="url(#bridge-arrow)" />
        <defs>
          <marker id="bridge-arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="#22c55e" />
          </marker>
        </defs>
        {targets.map((t, i) => {
          const x = 210 + i * 130
          return (
            <g key={t}>
              <rect x={x} y={36} width={120} height={68} rx={10} fill="#0f172a" stroke="#22c55e" strokeWidth={1.5} strokeDasharray="4 2" />
              <text x={x + 60} y={58} fill="#bbf7d0" fontSize={11} fontWeight={600} textAnchor="middle">
                C#
              </text>
              <text x={x + 60} y={78} fill="#86efac" fontSize={9} textAnchor="middle" fontFamily="JetBrains Mono, monospace">
                {shortProject(t)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
