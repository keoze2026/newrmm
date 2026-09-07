import { useEffect, useState } from 'react'
import { api, type AuditEvent, type HistoryEntry, type Session } from '../../lib/api'

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="w-full px-8 py-8">
      <h2 className="text-lg font-semibold text-navy">{title}</h2>
      <div className="mt-5">{children}</div>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong bg-white px-6 py-10 text-center text-sm text-muted">
      {children}
    </div>
  )
}

const FIELDS: { key: string; label: string }[] = [
  { key: 'hostname', label: 'Hostname' },
  { key: 'os', label: 'Operating system' },
  { key: 'os_version', label: 'Version' },
  { key: 'user', label: 'Logged-in user' },
  { key: 'ip', label: 'IP address' },
  { key: 'cpu', label: 'CPU' },
  { key: 'cores', label: 'Cores' },
  { key: 'memory', label: 'Memory' },
  { key: 'agent_version', label: 'Agent version' },
]

export function SystemInfoTab({ session }: { session: Session }) {
  const info = session.system_info ?? {}
  const hasInfo = Object.keys(info).length > 0

  return (
    <Panel title="System info">
      {!hasInfo ? (
        <Empty>The endpoint reports its system details when your guest joins.</Empty>
      ) : (
        <dl className="overflow-hidden rounded-xl border border-line bg-white">
          {FIELDS.map(({ key, label }) => (
            <div key={key} className="flex border-b border-line last:border-b-0">
              <dt className="w-52 shrink-0 bg-canvas px-4 py-2.5 text-sm text-muted">{label}</dt>
              <dd className="px-4 py-2.5 text-sm text-navy">
                {String((info as Record<string, unknown>)[key] ?? '—')}
              </dd>
            </div>
          ))}
          <div className="flex border-t border-line">
            <dt className="w-52 shrink-0 bg-canvas px-4 py-2.5 text-sm text-muted">Status</dt>
            <dd className="px-4 py-2.5 text-sm font-medium">
              <span className={session.guest_connected ? 'text-online' : 'text-muted'}>
                {session.guest_connected ? 'Connected' : 'Not connected'}
              </span>
            </dd>
          </div>
          <div className="flex border-t border-line">
            <dt className="w-52 shrink-0 bg-canvas px-4 py-2.5 text-sm text-muted">Last seen</dt>
            <dd className="px-4 py-2.5 text-sm text-navy">
              {session.guest_last_seen_at
                ? new Date(session.guest_last_seen_at).toLocaleString()
                : '—'}
            </dd>
          </div>
        </dl>
      )}
    </Panel>
  )
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

export function HistoryTab({ session }: { session: Session }) {
  const [rows, setRows] = useState<HistoryEntry[]>([])

  useEffect(() => {
    api.sessionHistory(session.id).then(setRows).catch(() => setRows([]))
  }, [session.id])

  return (
    <Panel title="Session history">
      {rows.length === 0 ? (
        <Empty>No past sessions recorded for this machine.</Empty>
      ) : (
        <table className="w-full overflow-hidden rounded-xl border border-line bg-white text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Start time</th>
              <th className="px-4 py-2.5 font-medium">Kind</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Duration</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-line">
                <td className="px-4 py-2.5 text-navy">
                  {new Date(row.started_at ?? row.created_at).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-muted">{row.kind}</td>
                <td className="px-4 py-2.5 text-muted">{row.state}</td>
                <td className="px-4 py-2.5 text-muted">{formatDuration(row.duration_seconds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

export function LogsTab({ session }: { session: Session }) {
  const [rows, setRows] = useState<AuditEvent[]>([])

  useEffect(() => {
    api.sessionLogs(session.id).then(setRows).catch(() => setRows([]))
  }, [session.id])

  return (
    <Panel title="Logs">
      {rows.length === 0 ? (
        <Empty>No server-side events recorded for this session yet.</Empty>
      ) : (
        <table className="w-full overflow-hidden rounded-xl border border-line bg-white text-left text-sm">
          <thead className="bg-canvas text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-4 py-2.5 font-medium">Time</th>
              <th className="px-4 py-2.5 font-medium">Action</th>
              <th className="px-4 py-2.5 font-medium">Actor</th>
              <th className="px-4 py-2.5 font-medium">Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-line align-top">
                <td className="whitespace-nowrap px-4 py-2.5 text-muted">
                  {new Date(row.ts).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 font-medium text-navy">{row.action}</td>
                <td className="px-4 py-2.5 text-muted">{row.actor_label || row.actor_type}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">
                  {Object.keys(row.detail).length ? JSON.stringify(row.detail) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

/** Terminal, Files and Download launch into the active session; until the guest
 *  joins they must say so plainly (Appendix A.6). */
export function LaunchTab({
  title,
  session,
  onJoin,
  description,
}: {
  title: string
  session: Session
  onJoin: () => void
  description: string
}) {
  return (
    <Panel title={title}>
      {session.guest_connected ? (
        <div className="rounded-xl border border-line bg-white px-6 py-10 text-center">
          <p className="text-sm text-navy">{description}</p>
          <button
            type="button"
            onClick={onJoin}
            className="mt-4 rounded-lg bg-primary px-6 py-2 text-sm font-semibold text-white transition hover:bg-primary-dark"
          >
            Open in viewer
          </button>
        </div>
      ) : (
        <Empty>{title} is available once your guest joins.</Empty>
      )}
    </Panel>
  )
}

export function NotImplementedTab({ title, note }: { title: string; note: string }) {
  return (
    <Panel title={title}>
      <Empty>
        <span className="font-medium text-navy">Not yet implemented.</span>
        <br />
        {note}
      </Empty>
    </Panel>
  )
}
