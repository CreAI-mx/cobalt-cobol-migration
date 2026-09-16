/** PhaseTimeline — vertical stepper of all 9 pipeline phases (design §Density 3).
 * Importer: Step5Migrate.tsx. No API change. RUNNING uses SpinnerIcon so the
 * last step shows a half-circle loader (user: "animaciones tipo loaders el tipo
 * medio circulo giratorio"). */
import type { PhaseEvent } from '../lib/api'
import { PHASES } from '../lib/phases'
import { AlertIcon, CheckIcon, GearIcon, SparkIcon, SpinnerIcon } from './Icons'

interface Props {
  phaseMap: Map<string, PhaseEvent>
  archAction?: string
  live?: boolean
}

export default function PhaseTimeline({ phaseMap, archAction, live = false }: Props) {
  return (
    <ol className="timeline" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {PHASES.map((meta) => {
        const ev = phaseMap.get(meta.id)
        const status = ev?.status
        const waiting = Boolean(
          live &&
            status === 'RUNNING' &&
            ev &&
            /^WAITING/i.test(ev.detail) &&
            archAction !== 'accepted',
        )
        const running = live && status === 'RUNNING'
        const iconClass = [
          'timeline-icon',
          meta.agentic ? 'agentic' : '',
          running ? 'running' : '',
          status === 'OK' ? 'ok' : '',
          status === 'BLOCKED' ? 'blocked' : '',
        ]
          .filter(Boolean)
          .join(' ')

        let icon = meta.agentic ? (
          <SparkIcon width={13} height={13} />
        ) : (
          <GearIcon width={13} height={13} />
        )
        if (running) icon = <SpinnerIcon width={13} height={13} />
        else if (status === 'OK') icon = <CheckIcon width={13} height={13} />
        else if (status === 'BLOCKED') icon = <AlertIcon width={13} height={13} />

        const statusLine = !ev
          ? 'pending'
          : waiting
            ? 'waiting for accept'
            : running && meta.runningLabel
              ? meta.runningLabel
              : ev.status.toLowerCase()

        const itemClass = [
          'timeline-item',
          running ? 'is-running' : '',
          status === 'OK' ? 'is-ok' : '',
          status === 'BLOCKED' ? 'is-blocked' : '',
        ]
          .filter(Boolean)
          .join(' ')

        const jumpToParity = () => {
          if (!meta.scrollTargetId) return
          document.getElementById(meta.scrollTargetId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }

        return (
          <li
            key={meta.id}
            className={`${itemClass}${meta.scrollTargetId ? ' timeline-item-jump' : ''}`}
            onClick={meta.scrollTargetId ? jumpToParity : undefined}
            onKeyDown={
              meta.scrollTargetId
                ? (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      jumpToParity()
                    }
                  }
                : undefined
            }
            role={meta.scrollTargetId ? 'button' : undefined}
            tabIndex={meta.scrollTargetId ? 0 : undefined}
            title={meta.scrollTargetId ? 'Jump to COBOL vs C# parity sandbox' : undefined}
          >
            <span className={iconClass}>{icon}</span>
            <div className="timeline-body">
              <div className="name">{meta.railTitle ?? `${meta.id} · ${meta.label}`}</div>
              <div className="skill">{meta.skill}</div>
              <div
                className={`status-line ${ev ? ev.status.toLowerCase() : ''}`}
                title={ev?.detail}
              >
                {statusLine}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
