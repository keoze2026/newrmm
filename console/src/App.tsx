import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DetailPanel from './components/DetailPanel'
import IconRail from './components/IconRail'
import SectionPanel from './components/SectionPanel'
import SessionList from './components/SessionList'
import Viewer from './components/Viewer'
import type { TabKey } from './components/TabStrip'
import LoginPage from './pages/LoginPage'
import { api, type Session } from './lib/api'
import { useAuth } from './lib/auth'
import { SessionStream, type StreamState } from './lib/stream'

const IDLE_STATE: StreamState = {
  connected: false,
  guestConnected: false,
  hostName: null,
  systemInfo: {},
  monitors: [],
  stats: { fps: 0, kbps: 0 },
}

export default function App() {
  const { operator, loading } = useAuth()
  const [sessions, setSessions] = useState<Session[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('session')
  const [search, setSearch] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [viewerOpen, setViewerOpen] = useState(false)
  const [frame, setFrame] = useState<ImageBitmap | null>(null)
  const [streamState, setStreamState] = useState<StreamState>(IDLE_STATE)
  const [renameRequest, setRenameRequest] = useState(0)

  const streamRef = useRef<SessionStream | null>(null)

  const refresh = useCallback(async () => {
    try {
      const rows = await api.listSessions()
      setSessions(rows)
      setError(null)
      setSelectedId((current) => current ?? rows[0]?.id ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load sessions')
    }
  }, [])

  useEffect(() => {
    if (!operator) return
    refresh()
    // Presence changes on the server, not in this tab, so poll it.
    const timer = window.setInterval(refresh, 4000)
    return () => window.clearInterval(timer)
  }, [operator, refresh])

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return sessions
    return sessions.filter(
      (s) =>
        s.name.toLowerCase().includes(needle) ||
        s.code.toLowerCase().includes(needle) ||
        (s.host_name ?? '').toLowerCase().includes(needle),
    )
  }, [sessions, search])

  const selected = useMemo(
    () => sessions.find((s) => s.id === selectedId) ?? null,
    [sessions, selectedId],
  )

  // One live stream at a time, following the selected session.
  useEffect(() => {
    streamRef.current?.close()
    streamRef.current = null
    setFrame(null)
    setStreamState(IDLE_STATE)

    if (!selected || selected.state === 'ended') return
    const stream = new SessionStream(
      selected.code,
      (bitmap) => setFrame(bitmap),
      (state) => setStreamState(state),
    )
    stream.connect()
    streamRef.current = stream
    return () => {
      stream.close()
    }
  }, [selected?.id, selected?.code, selected?.state])

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-canvas text-sm text-muted">
        Loading console…
      </div>
    )
  }

  if (!operator) return <LoginPage />

  async function createSession() {
    setCreating(true)
    try {
      const session = await api.createSession()
      await refresh()
      setSelectedId(session.id)
      setTab('session')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the session')
    } finally {
      setCreating(false)
    }
  }

  async function rename(name: string) {
    if (!selected) return
    await api.renameSession(selected.id, name)
    await refresh()
  }

  async function removeSelected() {
    const targets = checked.size > 0 ? [...checked] : selected ? [selected.id] : []
    if (targets.length === 0) return
    for (const id of targets) {
      try {
        await api.deleteSession(id)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not end the session')
      }
    }
    setChecked(new Set())
    if (selected && targets.includes(selected.id)) setSelectedId(null)
    await refresh()
  }

  function openViewer() {
    if (!selected?.guest_connected) return
    setViewerOpen(true)
  }

  return (
    <div className="flex h-full">
      <IconRail />
      <SectionPanel sessionCount={sessions.length} onCreate={createSession} creating={creating} />
      <SessionList
        sessions={visible}
        selectedId={selectedId}
        onSelect={(session) => {
          setSelectedId(session.id)
          setTab('session')
        }}
        onJoin={openViewer}
        onEdit={() => {
          setTab('session')
          setRenameRequest((n) => n + 1)
        }}
        onDelete={removeSelected}
        search={search}
        onSearch={setSearch}
        checked={checked}
        onToggleChecked={(id) =>
          setChecked((prev) => {
            const next = new Set(prev)
            if (next.has(id)) next.delete(id)
            else next.add(id)
            return next
          })
        }
        onToggleAll={(on) => setChecked(on ? new Set(visible.map((s) => s.id)) : new Set())}
      />
      <DetailPanel
        session={selected}
        tab={tab}
        onTab={setTab}
        onRename={rename}
        onJoin={openViewer}
        previewBitmap={frame}
        editRequest={renameRequest}
      />

      {error && (
        <div
          role="alert"
          className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white shadow-lg"
        >
          {error}
        </div>
      )}

      {viewerOpen && selected && streamRef.current && (
        <Viewer
          session={selected}
          stream={streamRef.current}
          state={streamState}
          frame={frame}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </div>
  )
}
