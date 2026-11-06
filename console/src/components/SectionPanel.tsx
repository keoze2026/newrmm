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
    <section className="hidden w-[300px] shrink-0 flex-col min-[1100px]:flex border-r border-line bg-white px-6 py-6">
      <h1 className="text-2xl font-semibold tracking-tight text-navy">Support</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted">
        Provide on-demand support for any device on the internet.
      </p>

      <button
        type="button"
        onClick={onCreate}
        disabled={creating}
        className="mt-5 w-full rounded-xl bg-gradient-to-b from-primary to-primary-dark px-4 py-2.5 text-sm font-semibold text-white shadow-[0_2px_8px_rgba(47,111,228,0.3)] transition hover:shadow-[0_4px_14px_rgba(47,111,228,0.4)] hover:brightness-105 active:scale-[0.98] disabled:opacity-60 disabled:hover:shadow-[0_2px_8px_rgba(47,111,228,0.3)]"
      >
        {creating ? 'Creating…' : 'Create +'}
      </button>

      <div className="mt-6 flex items-center justify-between rounded-xl border border-line bg-gradient-to-r from-primary-soft to-white px-3.5 py-3 shadow-sm">
        <span className="text-sm font-medium text-navy">My Sessions</span>
        <span
          data-testid="session-count"
          className="min-w-[24px] rounded-full bg-primary px-2 py-0.5 text-center text-xs font-semibold text-white shadow-sm"
        >
          {sessionCount}
        </span>
      </div>
    </section>
  )
}
