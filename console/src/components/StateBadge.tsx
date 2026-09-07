const STYLES: Record<string, string> = {
  pending: 'bg-amber-500/15 text-amber-300',
  active: 'bg-emerald-500/15 text-emerald-300',
  ended: 'bg-slate-600/25 text-slate-400',
  online: 'bg-emerald-500/15 text-emerald-300',
  offline: 'bg-slate-600/25 text-slate-400',
}

export default function StateBadge({ value }: { value: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[value] ?? STYLES.ended}`}>
      {value}
    </span>
  )
}
