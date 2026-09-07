import { useCallback, useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import StateBadge from '../components/StateBadge'
import { api, type Session } from '../lib/api'

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [justCreated, setJustCreated] = useState<Session | null>(null)

  const refresh = useCallback(async () => {
    try {
      setSessions(await api.listSessions())
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load sessions')
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function createAttended() {
    setCreating(true)
    try {
      const session = await api.createSession('attended')
      setJustCreated(session)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the session')
    } finally {
      setCreating(false)
    }
  }

  async function setState(session: Session, state: 'active' | 'ended') {
    try {
      await api.updateSessionState(session.id, state)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the session')
    }
  }

  return (
    <>
      <PageHeader
        title="Sessions"
        subtitle="Attended sessions are joined with a short code; unattended sessions target an enrolled device."
        actions={
          <button
            onClick={createAttended}
            disabled={creating}
            className="rounded-md bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-sky-400 disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'New attended session'}
          </button>
        }
      />

      <div className="px-8 py-6">
        {error && (
          <div role="alert" className="mb-4 rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {justCreated && (
          <div className="mb-6 rounded-lg border border-sky-500/30 bg-sky-500/10 px-5 py-4">
            <div className="text-xs uppercase tracking-wide text-sky-300">Session code</div>
            <div className="mt-1 font-mono text-3xl tracking-[0.3em] text-sky-200">
              {justCreated.code}
            </div>
            <p className="mt-2 text-sm text-slate-400">
              Give this code to the person you are helping. In Phase 2 their agent joins with it.
            </p>
          </div>
        )}

        {sessions.length === 0 ? (
          <p className="text-sm text-slate-500">No sessions yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-4 font-medium">Code</th>
                <th className="py-2 pr-4 font-medium">Mode</th>
                <th className="py-2 pr-4 font-medium">State</th>
                <th className="py-2 pr-4 font-medium">Created</th>
                <th className="py-2 pr-4 font-medium">Device</th>
                <th className="py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id} className="border-b border-slate-900">
                  <td className="py-2.5 pr-4 font-mono tracking-widest">{session.code}</td>
                  <td className="py-2.5 pr-4 text-slate-400">{session.mode}</td>
                  <td className="py-2.5 pr-4">
                    <StateBadge value={session.state} />
                  </td>
                  <td className="py-2.5 pr-4 text-slate-400">
                    {new Date(session.created_at).toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-xs text-slate-500">
                    {session.device_id ? session.device_id.slice(0, 8) : '—'}
                  </td>
                  <td className="py-2.5 text-right">
                    {session.state === 'pending' && (
                      <button
                        onClick={() => setState(session, 'active')}
                        className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                      >
                        Mark active
                      </button>
                    )}
                    {session.state === 'active' && (
                      <button
                        onClick={() => setState(session, 'ended')}
                        className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:bg-slate-800"
                      >
                        End
                      </button>
                    )}
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
