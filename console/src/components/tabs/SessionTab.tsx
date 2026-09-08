import { useEffect, useRef, useState } from 'react'
import { CopyIcon, HourglassIcon, PencilIcon } from '../icons'
import { joinLink, joinUrl, type Session } from '../../lib/api'
import type { FrameSource } from '../../lib/stream'

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value)
        } catch {
          /* clipboard blocked; the value is selectable on screen */
        }
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1400)
      }}
      className="flex items-center gap-1.5 rounded-md border border-line-strong px-2.5 py-1.5 text-xs text-navy transition hover:bg-canvas"
    >
      <CopyIcon width={15} height={15} />
      {copied ? 'Copied' : 'Copy'}
    </button>
  )
}

export default function SessionTab({
  session,
  onRename,
  onJoin,
  previewBitmap,
  previewSeq,
  editRequest,
}: {
  session: Session
  onRename: (name: string) => Promise<void>
  onJoin: () => void
  previewBitmap: FrameSource | null
  previewSeq: number
  editRequest: number
}) {
  const [invite, setInvite] = useState<'code' | 'link'>('code')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(session.name)
  const previewRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    setDraft(session.name)
    setEditing(false)
  }, [session.id, session.name])

  // The Edit action in the session-list toolbar opens the same rename field.
  useEffect(() => {
    if (editRequest > 0) setEditing(true)
  }, [editRequest])

  useEffect(() => {
    const canvas = previewRef.current
    if (!canvas || !previewBitmap) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    canvas.width = previewBitmap.width
    canvas.height = previewBitmap.height
    ctx.drawImage(previewBitmap, 0, 0)
  }, [previewBitmap, previewSeq])

  async function commitRename() {
    const next = draft.trim()
    setEditing(false)
    if (next && next !== session.name) await onRename(next)
    else setDraft(session.name)
  }

  const joined = session.guest_connected

  return (
    <div className="mx-auto w-full max-w-[640px] px-8 py-8">
      {/* Name: editable; the join code is never editable (Appendix A.5). */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-muted">Name:</span>
        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') {
                setDraft(session.name)
                setEditing(false)
              }
            }}
            aria-label="Session name"
            data-testid="session-name-input"
            className="flex-1 rounded-lg border border-primary bg-white px-3 py-1.5 text-sm font-semibold text-navy outline-none ring-2 ring-primary/20"
          />
        ) : (
          <div className="flex flex-1 items-center gap-2 rounded-lg border border-line-strong bg-white px-3 py-1.5">
            <span data-testid="session-name" className="flex-1 text-sm font-semibold text-navy">
              {session.name}
            </span>
            <button
              type="button"
              title="Rename session"
              aria-label="Rename session"
              data-testid="rename-session"
              onClick={() => setEditing(true)}
              className="text-muted transition hover:text-primary"
            >
              <PencilIcon width={16} height={16} />
            </button>
          </div>
        )}
      </div>

      <div className="mt-7">
        <div className="flex items-center gap-4">
          <span className="text-sm font-medium text-muted">Invite via:</span>
          <div className="flex gap-1 rounded-lg bg-canvas p-1">
            {(['code', 'link'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                data-testid={`invite-${mode}`}
                data-active={invite === mode}
                onClick={() => setInvite(mode)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium capitalize transition ${
                  invite === mode ? 'bg-white text-primary shadow-sm' : 'text-muted hover:text-navy'
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        {invite === 'code' ? (
          <div className="mt-4 rounded-xl border border-line bg-white px-6 py-7 text-center">
            <p className="text-sm text-muted">Direct guest to:</p>
            <p className="mt-1 text-base font-medium text-primary">{joinUrl()}</p>
            <p className="mt-6 text-sm text-muted">And instruct to type in the code:</p>
            <p
              data-testid="join-code"
              className="mt-1 font-mono text-4xl font-bold tracking-[0.18em] text-navy"
            >
              {session.code}
            </p>
            <div className="mt-6 flex justify-center">
              <CopyButton value={session.code} label="Copy the join code" />
            </div>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-line bg-white px-6 py-6">
            <label className="text-sm text-muted" htmlFor="join-link">
              Share this link with your guest:
            </label>
            <div className="mt-2 flex items-center gap-2">
              <input
                id="join-link"
                data-testid="join-link"
                readOnly
                value={joinLink(session.code)}
                className="flex-1 rounded-lg border border-line-strong bg-canvas px-3 py-2 text-sm text-navy outline-none"
              />
              <CopyButton value={joinLink(session.code)} label="Copy the join link" />
            </div>
          </div>
        )}
      </div>

      <div className="mt-8 flex justify-center">
        <button
          type="button"
          onClick={onJoin}
          disabled={!joined}
          data-testid="join-button"
          className="rounded-lg bg-primary px-10 py-2.5 text-sm font-semibold text-white transition hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-40"
        >
          Join
        </button>
      </div>

      <div className="mt-7 text-center">
        <p
          data-testid="waiting-line"
          className="flex items-center justify-center gap-2 text-sm font-medium text-navy"
        >
          <HourglassIcon width={17} height={17} className="text-muted" />
          {joined ? 'Your guest has joined.' : 'Your guest has not joined yet…'}
        </p>
        {!joined && (
          <p className="mx-auto mt-2 max-w-[440px] text-xs italic leading-relaxed text-muted">
            Once you and your guest join the session, you can control their screen. Click Join to
            launch the host client.
          </p>
        )}
      </div>

      {joined && (
        <div className="mt-8">
          <div className="mb-2 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-online" />
            <span className="text-xs font-semibold tracking-wide text-online">LIVE</span>
          </div>
          <button
            type="button"
            onClick={onJoin}
            data-testid="live-preview"
            title="Open the full viewer"
            className="block w-full overflow-hidden rounded-xl border border-line bg-navy transition hover:border-primary"
          >
            {previewBitmap ? (
              <canvas ref={previewRef} className="block w-full" />
            ) : (
              <div className="flex h-44 items-center justify-center text-sm text-white/70">
                Waiting for the first frame…
              </div>
            )}
          </button>
        </div>
      )}
    </div>
  )
}
