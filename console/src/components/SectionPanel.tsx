/** Column 2 (Appendix A.2). */
export default function SectionPanel({
  sessionCount,
  onCreate,
  creating,
}: {
  sessionCount: number
  onCreate: () => void
  creating: boolean
}) {
  return (
    <section className="flex w-[300px] shrink-0 flex-col border-r border-line bg-white px-6 py-6">
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Support</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Provide on-demand support for any device on the internet.
      </p>

      <button
        type="button"
        onClick={onCreate}
        disabled={creating}
        className="mt-5 w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-primary-dark disabled:opacity-60"
      >
        {creating ? 'Creating…' : 'Create +'}
      </button>

      <div className="mt-6 flex items-center justify-between rounded-lg bg-primary-soft px-3 py-2.5">
        <span className="text-sm font-medium text-navy">My Sessions</span>
        <span
          data-testid="session-count"
          className="min-w-[24px] rounded-full bg-primary px-2 py-0.5 text-center text-xs font-semibold text-white"
        >
          {sessionCount}
        </span>
      </div>
    </section>
  )
}
