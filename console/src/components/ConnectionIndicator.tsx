import { PersonIcon } from './icons'

/** Person - line - person. The line and second person go green once the guest
 *  is connected, grey otherwise (Appendix A.3). */
export default function ConnectionIndicator({ connected }: { connected: boolean }) {
  const tone = connected ? 'text-online' : 'text-line-strong'
  return (
    <span
      className="flex items-center gap-1"
      title={connected ? 'Guest connected' : 'Guest not connected'}
      data-testid="connection-indicator"
      data-connected={connected}
    >
      <PersonIcon width={16} height={16} className="text-muted" />
      <span className={`block h-[2px] w-5 rounded-full ${connected ? 'bg-online' : 'bg-line-strong'}`} />
      <PersonIcon width={16} height={16} className={tone} />
    </span>
  )
}
