import { useCallback, useEffect, useState, type FormEvent } from 'react'

/** The page the guest lands on (specification section 4).
 *
 *  "User receives a short code + link, runs a connector, and is instantly
 *  connected to the operator."
 *
 *  Unauthenticated by design: the person being helped has no account. It shows
 *  the code they were given, hands them the connector for their platform, and
 *  tells them what will happen before it happens.
 */

interface Build {
  platform: 'windows' | 'macos' | 'linux'
  label: string
  requirements: string
  available: boolean
  size: number | null
  sha256: string | null
}

interface SessionSummary {
  code: string
  name: string
  waiting: boolean
  connected: boolean
}

function detectPlatform(): Build['platform'] {
  const agent = navigator.userAgent
  if (/Windows/i.test(agent)) return 'windows'
  if (/Mac OS X|Macintosh/i.test(agent)) return 'macos'
  return 'linux'
}

function formatSize(bytes: number | null): string {
  if (!bytes) return ''
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export default function JoinPage() {
  const initialCode = (new URLSearchParams(window.location.search).get('code') ?? '')
    .toUpperCase()
    .trim()

  const [code, setCode] = useState(initialCode)
  const [session, setSession] = useState<SessionSummary | null>(null)
  const [builds, setBuilds] = useState<Build[]>([])
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const mine = detectPlatform()

  useEffect(() => {
    fetch('/api/connector')
      .then((r) => r.json())
      .then((body) => setBuilds(body.builds ?? []))
      .catch(() => setBuilds([]))
  }, [])

  const check = useCallback(async (value: string) => {
    const wanted = value.toUpperCase().trim()
    if (!wanted) return
    setChecking(true)
    setError(null)
    try {
      const response = await fetch(`/api/connector/session/${encodeURIComponent(wanted)}`)
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail ?? 'That session code is not valid')
      }
      setSession(await response.json())
    } catch (err) {
      setSession(null)
      setError(err instanceof Error ? err.message : 'That session code is not valid')
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    if (initialCode) check(initialCode)
  }, [initialCode, check])

  // Once the code is known, poll so the page notices the operator connecting.
  useEffect(() => {
    if (!session) return
    const timer = window.setInterval(() => {
      fetch(`/api/connector/session/${encodeURIComponent(session.code)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((body) => body && setSession(body))
        .catch(() => undefined)
    }, 4000)
    return () => window.clearInterval(timer)
  }, [session])

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    check(code)
  }

  const ordered = [...builds].sort((a, b) => (a.platform === mine ? -1 : b.platform === mine ? 1 : 0))

  return (
    <div className="h-full overflow-y-auto bg-canvas px-4 py-10">
      <div className="mx-auto w-full max-w-xl">
        <div className="flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-lg font-bold text-white">
            R
          </div>
          <h1 className="mt-4 text-xl font-semibold text-navy">Join a support session</h1>
          <p className="mt-1 text-center text-sm text-muted">
            Your support technician will have given you a code.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="mt-7 rounded-xl border border-line bg-white p-7 shadow-[0_2px_18px_rgba(31,58,95,0.08)]"
        >
          <label className="block text-[11px] font-semibold tracking-wide text-muted" htmlFor="code">
            SESSION CODE
          </label>
          <div className="mt-1.5 flex gap-2">
            <input
              id="code"
              data-testid="join-code-input"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="ABCD1234"
              autoComplete="off"
              className="flex-1 rounded-lg border border-line-strong bg-white px-3 py-2.5 font-mono text-lg tracking-[0.2em] text-navy outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
            <button
              type="submit"
              disabled={checking}
              className="rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-primary-dark disabled:opacity-60"
            >
              {checking ? 'Checking…' : 'Continue'}
            </button>
          </div>

          {error && (
            <div role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {session && (
            <div
              data-testid="join-session-found"
              className="mt-5 rounded-lg border border-primary/30 bg-primary-soft px-4 py-3"
            >
              <p className="text-sm font-medium text-navy">
                Session <span className="font-mono">{session.code}</span> found.
              </p>
              <p className="mt-1 text-xs text-muted">
                {session.connected
                  ? 'You are connected. You can close this page.'
                  : 'Download the connector below and run it to start.'}
              </p>
            </div>
          )}
        </form>

        {session && (
          <div className="mt-6 rounded-xl border border-line bg-white p-7">
            <h2 className="text-sm font-semibold text-navy">Download the connector</h2>
            <p className="mt-1 text-sm text-muted">
              Run it, then type your code when it asks. It will ask your permission before
              anything is shared.
            </p>

            <div className="mt-4 space-y-2">
              {ordered.map((build) => (
                <div
                  key={build.platform}
                  data-testid={`connector-${build.platform}`}
                  className="flex items-center gap-3 rounded-lg border border-line px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-navy">
                      {build.label}
                      {build.platform === mine && (
                        <span className="ml-2 rounded-full bg-primary-soft px-2 py-0.5 text-[11px] font-semibold text-primary">
                          your system
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted">
                      {build.requirements}
                      {build.available && build.size ? ` · ${formatSize(build.size)}` : ''}
                    </div>
                  </div>
                  {build.available ? (
                    <a
                      href={`/api/connector/${build.platform}?code=${encodeURIComponent(session.code)}`}
                      className="shrink-0 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary-dark"
                    >
                      Download
                    </a>
                  ) : (
                    <span className="shrink-0 text-xs text-muted">Not available</span>
                  )}
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-lg bg-canvas px-4 py-3">
              <h3 className="text-xs font-semibold text-navy">What happens next</h3>
              <ol className="mt-2 space-y-1 text-xs leading-relaxed text-muted">
                <li>1. Run the connector you downloaded.</li>
                <li>
                  2. Enter the code <span className="font-mono text-navy">{session.code}</span>.
                </li>
                <li>3. It asks your permission. Nothing is shared until you allow it.</li>
                <li>4. An icon stays in your system tray for as long as the session runs.</li>
                <li>5. Close the connector, or use its tray menu, to end the session.</li>
              </ol>
            </div>
          </div>
        )}

        <p className="mt-6 text-center text-xs text-muted">
          Only run a connector if you asked for support and recognise who you are talking to.
        </p>
      </div>
    </div>
  )
}
