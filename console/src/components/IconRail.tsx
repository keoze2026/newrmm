import { BellIcon, SupportIcon } from './icons'
import { useAuth } from '../lib/auth'

/** Column 1 (Appendix A.2): brand tile, Support nav, bell + avatar pinned low. */
export default function IconRail() {
  const { operator, logout } = useAuth()
  const initial = (operator?.full_name || operator?.email || '?').trim().charAt(0).toUpperCase()

  return (
    <nav className="hidden w-[74px] shrink-0 flex-col items-center min-[1100px]:flex border-r border-line bg-white py-4">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-dark text-lg font-bold text-white shadow-[0_4px_12px_rgba(47,111,228,0.35)]">
        R
      </div>

      <button
        type="button"
        aria-current="page"
        className="mt-6 flex w-[62px] flex-col items-center gap-1 rounded-xl bg-primary-soft py-2.5 text-primary shadow-sm"
      >
        <SupportIcon width={22} height={22} />
        <span className="text-[11px] font-semibold">Support</span>
      </button>

      <div className="flex-1" />

      <button
        type="button"
        title="Notifications"
        aria-label="Notifications"
        className="mb-3 flex h-9 w-9 items-center justify-center rounded-full text-muted transition hover:scale-105 hover:bg-canvas hover:text-navy active:scale-95"
      >
        <BellIcon />
      </button>

      <button
        type="button"
        onClick={logout}
        data-testid="user-avatar"
        title={`${operator?.email} — sign out`}
        aria-label={`${operator?.email} — sign out`}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-navy to-[#2a4d7a] text-sm font-semibold text-white shadow-sm transition hover:scale-105 active:scale-95"
      >
        {initial}
      </button>
    </nav>
  )
}
