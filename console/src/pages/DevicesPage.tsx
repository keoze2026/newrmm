import { useCallback, useEffect, useState, type FormEvent } from 'react'
import PageHeader from '../components/PageHeader'
import StateBadge from '../components/StateBadge'
import { api, type Device } from '../lib/api'

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([])
  const [name, setName] = useState('')
  const [os, setOs] = useState<Device['os']>('windows')
  const [secret, setSecret] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      setDevices(await api.listDevices())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load devices')
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  async function enroll(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const device = await api.enrollDevice(name, os)
      setSecret(device.enrollment_secret)
      setName('')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not enroll the device')
    }
  }

  return (
    <>
      <PageHeader
        title="Devices"
        subtitle="Enrolled endpoints for unattended access. The agent that uses these credentials arrives in Phase 2."
      />

      <div className="px-8 py-6">
        <form onSubmit={enroll} className="mb-6 flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-400" htmlFor="device-name">
              Device name
            </label>
            <input
              id="device-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Reception PC"
              className="mt-1 w-56 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400" htmlFor="device-os">
              Operating system
            </label>
            <select
              id="device-os"
              value={os}
              onChange={(e) => setOs(e.target.value as Device['os'])}
              className="mt-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm outline-none focus:border-sky-500"
            >
              <option value="windows">Windows</option>
              <option value="macos">macOS</option>
              <option value="linux">Linux</option>
            </select>
          </div>
          <button
            type="submit"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
          >
            Enroll device
          </button>
        </form>

        {error && (
          <div role="alert" className="mb-4 rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {error}
          </div>
        )}

        {secret && (
          <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-5 py-4">
            <div className="text-xs uppercase tracking-wide text-amber-300">
              Enrollment secret — shown once
            </div>
            <div className="mt-1 break-all font-mono text-sm text-amber-100">{secret}</div>
            <p className="mt-2 text-xs text-slate-400">
              The relay stores only an Argon2 hash of this value; it cannot be shown again.
            </p>
          </div>
        )}

        {devices.length === 0 ? (
          <p className="text-sm text-slate-500">No devices enrolled yet.</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 pr-4 font-medium">Name</th>
                <th className="py-2 pr-4 font-medium">OS</th>
                <th className="py-2 pr-4 font-medium">Status</th>
                <th className="py-2 pr-4 font-medium">Enrolled</th>
                <th className="py-2 font-medium">Last seen</th>
              </tr>
            </thead>
            <tbody>
              {devices.map((device) => (
                <tr key={device.id} className="border-b border-slate-900">
                  <td className="py-2.5 pr-4">{device.name}</td>
                  <td className="py-2.5 pr-4 text-slate-400">{device.os}</td>
                  <td className="py-2.5 pr-4">
                    <StateBadge value={device.status} />
                  </td>
                  <td className="py-2.5 pr-4 text-slate-400">
                    {new Date(device.enrolled_at).toLocaleString()}
                  </td>
                  <td className="py-2.5 text-slate-500">
                    {device.last_seen_at ? new Date(device.last_seen_at).toLocaleString() : '—'}
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
