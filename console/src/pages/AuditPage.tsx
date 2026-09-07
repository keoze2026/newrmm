import { useCallback, useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import { api, type AuditEvent } from '../lib/api'

const ACTION_COLOURS: Record<string, string> = {
  'auth.login.success': 'text-emerald-300',
  'auth.login.failed': 'text-red-300',
  'session.created': 'text-sky-300',
  'session.state_changed': 'text-sky-300',
  'device.enrolled': 'text-amber-300',
}

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setEvents(await api.listAudit())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the audit log')
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Append-only. The database rejects any update or delete on these rows."
        actions={
          <button
            onClick={refresh}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          >
            Refresh
          </button>
        }
      />

      <div className="px-8 py-6">
        {error && (
          <div role="alert" className="mb-4 rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {events.length === 0 ? (
          <p className="text-sm text-slate-500">No audit events yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-4 font-medium">Time</th>
                <th className="py-2 pr-4 font-medium">Action</th>
                <th className="py-2 pr-4 font-medium">Actor</th>
                <th className="py-2 pr-4 font-medium">Target</th>
                <th className="py-2 pr-4 font-medium">IP</th>
                <th className="py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id} className="border-b border-slate-900 align-top">
                  <td className="whitespace-nowrap py-2.5 pr-4 text-slate-400">
                    {new Date(event.ts).toLocaleString()}
                  </td>
                  <td className={`py-2.5 pr-4 font-medium ${ACTION_COLOURS[event.action] ?? 'text-slate-300'}`}>
                    {event.action}
                  </td>
                  <td className="py-2.5 pr-4 text-slate-400">{event.actor_label || event.actor_type}</td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-slate-500">
                    {event.target_type ? `${event.target_type}:${event.target_id?.slice(0, 8)}` : '—'}
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-slate-500">{event.ip ?? '—'}</td>
                  <td className="py-2.5 font-mono text-xs text-slate-500">
                    {Object.keys(event.detail).length ? JSON.stringify(event.detail) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
