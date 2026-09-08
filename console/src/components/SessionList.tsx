import { useMemo, useState } from 'react'
import ConnectionIndicator from './ConnectionIndicator'
import { CaretIcon, DeleteIcon, EditIcon, JoinIcon, MoreIcon, SearchIcon } from './icons'
import type { Session } from '../lib/api'

/** Column 3 (Appendix A.2 and A.3). */
export default function SessionList({
  sessions,
  selectedId,
  onSelect,
  onJoin,
  onEdit,
  onDelete,
  search,
  onSearch,
  checked,
  onToggleChecked,
  onToggleAll,
}: {
  sessions: Session[]
  selectedId: string | null
  onSelect: (session: Session) => void
  onJoin: () => void
  onEdit: () => void
  onDelete: () => void
  search: string
  onSearch: (value: string) => void
  checked: Set<string>
  onToggleChecked: (id: string) => void
  onToggleAll: (on: boolean) => void
}) {
  const [moreOpen, setMoreOpen] = useState(false)
  const allChecked = useMemo(
    () => sessions.length > 0 && sessions.every((s) => checked.has(s.id)),
    [sessions, checked],
  )
  const selected = sessions.find((s) => s.id === selectedId) ?? null
  const canJoin = Boolean(selected?.guest_connected)

  const action =
    'flex shrink-0 items-center gap-1 rounded-md px-1.5 py-1 text-xs text-navy transition hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-40'

  return (
    <section className="flex w-[392px] shrink-0 flex-col border-r border-line bg-white">
      <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-3">
        <h2 className="shrink-0 whitespace-nowrap text-sm font-semibold text-navy">My Sessions</h2>
        <div className="relative flex items-center gap-0.5">
          <button type="button" data-testid="list-join" className={action} onClick={onJoin} disabled={!canJoin} title="Join">
            <JoinIcon width={16} height={16} />
            Join
          </button>
          <button type="button" data-testid="list-edit" className={action} onClick={onEdit} disabled={!selected} title="Edit">
            <EditIcon width={16} height={16} />
            Edit
          </button>
          <button
            type="button"
            data-testid="list-delete"
            className={action}
            onClick={onDelete}
            disabled={checked.size === 0 && !selected}
            title="Delete"
          >
            <DeleteIcon width={16} height={16} />
            Delete
          </button>
          <button
            type="button"
            className={action}
            data-testid="list-more"
            onClick={() => setMoreOpen((v) => !v)}
            title="More"
            aria-expanded={moreOpen}
          >
            <MoreIcon width={16} height={16} />
            More
          </button>
          {moreOpen && (
            <div className="absolute right-0 top-8 z-10 w-44 rounded-lg border border-line bg-white py-1 shadow-lg">
              <p className="px-3 py-2 text-xs text-muted">
                Additional bulk actions are not built yet.
              </p>
            </div>
          )}
        </div>
      </header>

      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <label className="flex items-center gap-1 text-muted">
          <input
            type="checkbox"
            aria-label="Select all sessions"
            checked={allChecked}
            onChange={(e) => onToggleAll(e.target.checked)}
            className="h-4 w-4 accent-[#2f6fe4]"
          />
          <CaretIcon width={16} height={16} />
        </label>

        <div className="relative flex-1">
          <SearchIcon
            width={16}
            height={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted"
          />
          <input
            type="search"
            placeholder="Search My Sessions"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="w-full rounded-full border border-line-strong bg-white py-1.5 pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          />
        </div>
      </div>

      <ul className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <li className="px-4 py-6 text-sm text-muted">
            No sessions yet. Use <span className="font-medium text-navy">Create +</span> to start one.
          </li>
        )}
        {sessions.map((session) => {
          const isSelected = session.id === selectedId
          return (
            <li key={session.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSelect(session)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') onSelect(session)
                }}
                data-testid="session-row"
                data-code={session.code}
                data-selected={isSelected}
                className={`flex cursor-pointer items-center gap-3 border-b border-line px-4 py-3 transition ${
                  isSelected ? 'bg-primary-soft' : 'hover:bg-canvas'
                }`}
              >
                <input
                  type="checkbox"
                  aria-label={`Select ${session.name}`}
                  checked={checked.has(session.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => onToggleChecked(session.id)}
                  className="h-4 w-4 accent-[#2f6fe4]"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-navy">{session.name}</div>
                  <div className="truncate text-xs text-muted">
                    Host: {session.host_name ?? '—'}
                  </div>
                </div>
                <ConnectionIndicator connected={session.guest_connected} />
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
