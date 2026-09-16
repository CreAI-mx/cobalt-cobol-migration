/** Stacked bar: whole repo composition (not COBOL-only). */
import type { ExplorationPack } from '../lib/api'

export default function EstateCompositionBar({ pack }: { pack: ExplorationPack }) {
  const s = pack.inventory_summary
  const other = Math.max(0, s.files - s.programs - s.copybooks)
  const total = s.files || 1
  const segs = [
    { key: 'cobol', n: s.programs, cls: 'estate-seg--cobol', label: 'COBOL' },
    { key: 'cpy', n: s.copybooks, cls: 'estate-seg--cpy', label: 'Copybooks' },
    { key: 'other', n: other, cls: 'estate-seg--other', label: 'Other' },
  ].filter((x) => x.n > 0)
  return (
    <div className="estate-composition" role="img" aria-label="Repository file composition">
      <div className="estate-composition-track">
        {segs.map((seg) => (
          <div
            key={seg.key}
            className={`estate-seg ${seg.cls}`}
            style={{ flexGrow: seg.n, flexBasis: `${(seg.n / total) * 100}%` }}
            title={`${seg.label}: ${seg.n}`}
          />
        ))}
      </div>
      <div className="estate-composition-legend">
        {segs.map((seg) => (
          <span key={seg.key} className="estate-legend-item">
            <span className={`estate-legend-swatch ${seg.cls}`} />
            <span className="mono">{seg.n}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
