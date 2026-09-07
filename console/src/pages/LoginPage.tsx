import { useState, type FormEvent } from 'react'
import { useAuth } from '../lib/auth'

export default function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-canvas px-4">
      {/* Enter submits: the button is the form's submit control. */}
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-xl border border-line bg-white p-8 shadow-[0_2px_18px_rgba(31,58,95,0.08)]"
      >
        <div className="flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-lg font-bold text-white">
            R
          </div>
          <h1 className="mt-4 text-xl font-semibold text-navy">RMM Console</h1>
          <p className="mt-1 text-sm text-muted">Sign in to your monitoring server</p>
        </div>

        <label className="mt-7 block text-[11px] font-semibold tracking-wide text-muted" htmlFor="email">
          EMAIL
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-line-strong bg-white px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        />

        <label className="mt-4 block text-[11px] font-semibold tracking-wide text-muted" htmlFor="password">
          PASSWORD
        </label>
        <input
          id="password"
          type="password"
          required
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-line-strong bg-white px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
        />

        {error && (
          <div role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy}
          className="mt-6 w-full rounded-lg bg-primary px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-primary-dark disabled:opacity-60"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="mt-6 text-center text-xs text-muted">
          The first account registered on a server becomes the admin.
        </p>
      </form>
    </div>
  )
}
