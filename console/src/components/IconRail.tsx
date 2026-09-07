import { BellIcon, SupportIcon } from './icons'
import { useAuth } from '../lib/auth'

/** Column 1 (Appendix A.2): brand tile, Support nav, bell + avatar pinned low. */
export default function IconRail() {
  const { operator, logout } = useAuth()
  const initial = (operator?.full_name || operator?.email || '?').trim().charAt(0).toUpperCase()

  return (
    <nav className="flex w-[74px] shrink-0 flex-col items-center border-r border-line bg-white py-3">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-lg font-bold text-white">
        R
      </div>

      <button
        type="button"
        aria-current="page"
        className="mt-5 flex w-[62px] flex-col items-center gap-1 rounded-lg bg-primary-soft py-2 text-primary"
      >
        <SupportIcon width={22} height={22} />
        <span className="text-[11px] font-semibold">Support</span>
      </button>

      <div className="flex-1" />

      <button
        type="button"
        title="Notifications"
        aria-label="Notifications"
        className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-canvas hover:text-navy"
      >
        <BellIcon />
      </button>

      <button
        type="button"
        onClick={logout}
        data-testid="user-avatar"
        title={`${operator?.email} — sign out`}
        aria-label={`${operator?.email} — sign out`}
        className="flex h-9 w-9 items-center justify-center rounded-full bg-navy text-sm font-semibold text-white"
      >
        {initial}
      </button>
    </nav>
  )
}
