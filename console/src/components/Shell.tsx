import { useEffect, useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

const NAV = [
  { to: '/sessions', label: 'Sessions' },
  { to: '/devices', label: 'Devices' },
  { to: '/audit', label: 'Audit log' },
]

export default function Shell({ children }: { children: ReactNode }) {
  const { operator, logout } = useAuth()
  const [health, setHealth] = useState<string>('…')

  useEffect(() => {
    const check = () => api.health().then((h) => setHealth(h.status)).catch(() => setHealth('unreachable'))
    check()
    const timer = setInterval(check, 30000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100">
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-900/50">
        <div className="border-b border-slate-800 px-5 py-4">
          <div className="text-sm font-semibold tracking-tight">Remote Support</div>
          <div className="text-xs text-slate-500">Operator console</div>
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm transition ${
                  isActive ? 'bg-sky-500/15 text-sky-300' : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-800 p-3 text-xs">
          <div className="flex items-center gap-2 px-2 pb-2 text-slate-500">
            <span
              className={`h-2 w-2 rounded-full ${health === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'}`}
              title={`relay: ${health}`}
            />
            relay {health}
          </div>
          <div className="truncate px-2 pb-2 text-slate-400">{operator?.email}</div>
          <button
            onClick={logout}
            className="w-full rounded-md border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  )
}
