import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AnnotateIcon,
  ClearIcon,
  ClipboardIcon,
  ClipboardPullIcon,
  CloseIcon,
  DownloadIcon,
  EyeSlashIcon,
  FilesIcon,
  FullscreenIcon,
  MonitorSwitchIcon,
  PointerIcon,
  ScreenshotIcon,
  TerminalIcon,
  UploadIcon,
  ZoomInIcon,
  ZoomOutIcon,
} from './icons'
import FilesPanel from './viewer/FilesPanel'
import TerminalPanel from './viewer/TerminalPanel'
import type { Session } from '../lib/api'
import type { SessionStream, StreamState } from '../lib/stream'

interface Rect {
  dx: number
  dy: number
  dw: number
  dh: number
}

const KEY_MODIFIERS = ['Shift', 'Control', 'Alt', 'Meta']

export default function Viewer({
  session,
  stream,
  state,
  frame,
  onClose,
}: {
  session: Session
  stream: SessionStream
  state: StreamState
  frame: ImageBitmap | null
  onClose: () => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const screenRef = useRef<HTMLCanvasElement>(null)
  const annotationRef = useRef<HTMLCanvasElement>(null)
  const rectRef = useRef<Rect>({ dx: 0, dy: 0, dw: 0, dh: 0 })
  const drawingRef = useRef(false)

  const [controlling, setControlling] = useState(true)
  const [zoom, setZoom] = useState(1)
  const [annotating, setAnnotating] = useState(false)
  const [blanked, setBlanked] = useState(false)
  const [panel, setPanel] = useState<'none' | 'terminal' | 'files'>('none')
  const [monitorMenu, setMonitorMenu] = useState(false)
  const [monitor, setMonitor] = useState(0)
  const [notice, setNotice] = useState<string | null>(null)

  const flash = useCallback((message: string) => {
    setNotice(message)
    window.setTimeout(() => setNotice(null), 2600)
  }, [])

  /** Draw the frame letterboxed inside the viewer, preserving aspect ratio. */
  const paint = useCallback(() => {
    const canvas = screenRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const width = container.clientWidth
    const height = container.clientHeight
    const dpr = window.devicePixelRatio || 1
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr
      canvas.height = height * dpr
      const overlay = annotationRef.current
      if (overlay) {
        overlay.width = width * dpr
        overlay.height = height * dpr
      }
    }

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = '#0d1726'
    ctx.fillRect(0, 0, width, height)

    if (!frame) return
    const scale = Math.min(width / frame.width, height / frame.height) * zoom
    const dw = frame.width * scale
    const dh = frame.height * scale
    const dx = (width - dw) / 2
    const dy = (height - dh) / 2
    rectRef.current = { dx, dy, dw, dh }
    ctx.drawImage(frame, dx, dy, dw, dh)
  }, [frame, zoom])

  useEffect(() => {
    paint()
  }, [paint])

  useEffect(() => {
    const onResize = () => paint()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [paint])

  // Close any shell the operator opened when the viewer itself closes.
  useEffect(() => {
    return () => {
      stream.send({ type: 'terminal', action: 'close' })
    }
  }, [stream])

  /** Screen point -> guest point, 0..1. Correct even when letterboxed. */
  const toGuest = useCallback((clientX: number, clientY: number) => {
    const canvas = screenRef.current
    if (!canvas) return null
    const bounds = canvas.getBoundingClientRect()
    const { dx, dy, dw, dh } = rectRef.current
    if (dw === 0 || dh === 0) return null
    const x = (clientX - bounds.left - dx) / dw
    const y = (clientY - bounds.top - dy) / dh
    if (x < 0 || x > 1 || y < 0 || y > 1) return null
    return { x, y }
  }, [])

  const annotate = useCallback((clientX: number, clientY: number, begin: boolean) => {
    const overlay = annotationRef.current
    if (!overlay) return
    const ctx = overlay.getContext('2d')
    if (!ctx) return
    const bounds = overlay.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    const x = (clientX - bounds.left) * dpr
    const y = (clientY - bounds.top) * dpr
    ctx.strokeStyle = '#ff3b30'
    ctx.lineWidth = 3 * dpr
    ctx.lineCap = 'round'
    if (begin) {
      ctx.beginPath()
      ctx.moveTo(x, y)
    } else {
      ctx.lineTo(x, y)
      ctx.stroke()
    }
  }, [])

  function onPointerDown(event: React.PointerEvent) {
    if (annotating) {
      drawingRef.current = true
      annotate(event.clientX, event.clientY, true)
      return
    }
    if (!controlling) return
    const point = toGuest(event.clientX, event.clientY)
    if (!point) return
    stream.send({
      type: 'input',
      kind: 'mouse',
      action: 'down',
      button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left',
      ...point,
    })
  }

  function onPointerMove(event: React.PointerEvent) {
    if (annotating) {
      if (drawingRef.current) annotate(event.clientX, event.clientY, false)
      return
    }
    if (!controlling) return
    const point = toGuest(event.clientX, event.clientY)
    if (!point) return
    stream.send({ type: 'input', kind: 'mouse', action: 'move', ...point })
  }

  function onPointerUp(event: React.PointerEvent) {
    if (annotating) {
      drawingRef.current = false
      return
    }
    if (!controlling) return
    const point = toGuest(event.clientX, event.clientY)
    if (!point) return
    stream.send({
      type: 'input',
      kind: 'mouse',
      action: 'up',
      button: event.button === 2 ? 'right' : event.button === 1 ? 'middle' : 'left',
      ...point,
    })
  }

  function onWheel(event: React.WheelEvent) {
    if (!controlling) return
    stream.send({ type: 'input', kind: 'scroll', dx: event.deltaX, dy: event.deltaY })
  }

  useEffect(() => {
    if (!controlling) return
    const modifiers = (e: KeyboardEvent) =>
      KEY_MODIFIERS.filter((m) => (e.getModifierState ? e.getModifierState(m) : false))

    /** Keys typed into the terminal or a file field belong to that field, not
     *  to the guest's screen. */
    const isEditing = (target: EventTarget | null) => {
      const node = target as HTMLElement | null
      if (!node) return false
      const tag = node.tagName
      return (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        node.isContentEditable === true
      )
    }

    const down = (event: KeyboardEvent) => {
      if (event.key === 'Escape' || isEditing(event.target)) return
      event.preventDefault()
      stream.send({ type: 'input', kind: 'key', action: 'down', key: event.key, modifiers: modifiers(event) })
    }
    const up = (event: KeyboardEvent) => {
      if (event.key === 'Escape' || isEditing(event.target)) return
      event.preventDefault()
      stream.send({ type: 'input', kind: 'key', action: 'up', key: event.key, modifiers: modifiers(event) })
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [controlling, stream])

  function screenshot() {
    const canvas = screenRef.current
    if (!canvas) return
    const link = document.createElement('a')
    link.download = `${session.name}-${new Date().toISOString().replace(/[:.]/g, '-')}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()
    flash('Screenshot saved.')
  }

  function toggleFullscreen() {
    const node = containerRef.current?.parentElement
    if (!node) return
    if (document.fullscreenElement) document.exitFullscreen()
    else node.requestFullscreen().catch(() => flash('Fullscreen was refused by the browser.'))
  }

  function clearAnnotations() {
    const overlay = annotationRef.current
    const ctx = overlay?.getContext('2d')
    if (overlay && ctx) ctx.clearRect(0, 0, overlay.width, overlay.height)
  }

  async function pushClipboard() {
    try {
      const text = await navigator.clipboard.readText()
      stream.send({ type: 'clipboard', action: 'set', text })
      flash('Clipboard sent to the endpoint.')
    } catch {
      flash('The browser would not share your clipboard.')
    }
  }

  function pullClipboard() {
    const unsubscribe = stream.subscribe(async (message) => {
      if (message.type !== 'clipboard' || message.action !== 'text') return
      unsubscribe()
      const text = String(message.text ?? '')
      try {
        await navigator.clipboard.writeText(text)
        flash(text ? 'Endpoint clipboard copied to yours.' : 'The endpoint clipboard is empty.')
      } catch {
        flash('Could not write to your clipboard.')
      }
    })
    stream.send({ type: 'clipboard', action: 'get' })
  }

  function toggleBlank() {
    const next = !blanked
    setBlanked(next)
    stream.send({ type: 'blank', on: next })
  }

  const tool =
    'flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] text-white/85 transition hover:bg-white/10'
  const toolActive = 'bg-white/15 text-white'

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0d1726]">
      <header data-testid="viewer-toolbar" className="flex h-12 shrink-0 items-center gap-3 border-b border-white/10 px-3">
        <span className="flex items-center gap-2 text-sm font-semibold text-white">
          <span
            className={`h-2 w-2 rounded-full ${state.guestConnected ? 'bg-online' : 'bg-white/40'}`}
            data-testid="viewer-status-dot"
          />
          {state.hostName ?? session.host_name ?? session.name}
        </span>
        <span data-testid="viewer-stats" className="font-mono text-xs text-white/60">
          {state.stats.fps} fps · {state.stats.kbps} kbps
        </span>

        <div className="flex-1" />

        <div className="flex items-center gap-0.5">
          <button
            type="button"
            data-testid="toggle-control"
            onClick={() => setControlling((v) => !v)}
            className={`${tool} ${controlling ? toolActive : ''}`}
            title={controlling ? 'Controlling — click for view only' : 'View only — click to control'}
          >
            <PointerIcon width={16} height={16} />
            {controlling ? 'Controlling' : 'View'}
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === 'terminal' ? 'none' : 'terminal')}
            className={`${tool} ${panel === 'terminal' ? toolActive : ''}`}
            title="Terminal"
          >
            <TerminalIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={() => setPanel(panel === 'files' ? 'none' : 'files')}
            className={`${tool} ${panel === 'files' ? toolActive : ''}`}
            title="Files"
          >
            <FilesIcon width={16} height={16} />
          </button>
          <button type="button" onClick={screenshot} className={tool} title="Screenshot">
            <ScreenshotIcon width={16} height={16} />
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => setMonitorMenu((v) => !v)}
              className={`${tool} ${monitorMenu ? toolActive : ''}`}
              title="Switch monitor"
              data-testid="monitor-switch"
            >
              <MonitorSwitchIcon width={16} height={16} />
            </button>
            {monitorMenu && (
              <div className="absolute right-0 top-9 z-10 w-52 rounded-lg border border-white/10 bg-[#16233a] py-1 text-sm text-white/85 shadow-xl">
                {(state.monitors.length ? state.monitors : [{ index: 0, label: 'Primary', width: 0, height: 0 }]).map(
                  (m) => (
                    <button
                      key={m.index}
                      type="button"
                      onClick={() => {
                        setMonitor(m.index)
                        stream.send({ type: 'monitor', index: m.index })
                        setMonitorMenu(false)
                      }}
                      className={`block w-full px-3 py-2 text-left hover:bg-white/10 ${
                        monitor === m.index ? 'text-primary' : ''
                      }`}
                    >
                      {m.label || `Monitor ${m.index + 1}`}
                      {m.width ? ` — ${m.width}×${m.height}` : ''}
                    </button>
                  ),
                )}
              </div>
            )}
          </div>

          <button type="button" onClick={() => setZoom((z) => Math.min(4, z * 1.25))} className={tool} title="Zoom in">
            <ZoomInIcon width={16} height={16} />
          </button>
          <button type="button" onClick={() => setZoom((z) => Math.max(0.25, z / 1.25))} className={tool} title="Zoom out">
            <ZoomOutIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={() => setAnnotating((v) => !v)}
            className={`${tool} ${annotating ? toolActive : ''}`}
            title="Annotate"
            data-testid="annotate"
          >
            <AnnotateIcon width={16} height={16} />
          </button>
          <button type="button" onClick={clearAnnotations} className={tool} title="Clear annotations">
            <ClearIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={() => setPanel('files')}
            className={tool}
            title="Send file"
            data-testid="send-file"
          >
            <UploadIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={() => setPanel('files')}
            className={tool}
            title="Get file"
            data-testid="get-file"
          >
            <DownloadIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={pushClipboard}
            className={tool}
            title="Send clipboard to the endpoint"
            data-testid="clipboard-push"
          >
            <ClipboardIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={pullClipboard}
            className={tool}
            title="Get clipboard from the endpoint"
            data-testid="clipboard-pull"
          >
            <ClipboardPullIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={toggleBlank}
            className={`${tool} ${blanked ? toolActive : ''}`}
            title="Blank the guest screen"
            data-testid="blank-toggle"
          >
            <EyeSlashIcon width={16} height={16} />
          </button>
          <button type="button" onClick={toggleFullscreen} className={tool} title="Fullscreen">
            <FullscreenIcon width={16} height={16} />
          </button>
          <button
            type="button"
            onClick={onClose}
            className={`${tool} hover:bg-red-500/80`}
            title="End session view"
            data-testid="viewer-end"
          >
            <CloseIcon width={16} height={16} />
          </button>
        </div>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div ref={containerRef} className="absolute inset-0">
          <canvas
            ref={screenRef}
            data-testid="viewer-canvas"
            className={`absolute inset-0 h-full w-full ${
              annotating ? 'cursor-crosshair' : controlling ? 'cursor-none' : 'cursor-default'
            }`}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onWheel={onWheel}
            onContextMenu={(e) => e.preventDefault()}
          />
          <canvas ref={annotationRef} className="pointer-events-none absolute inset-0 h-full w-full" />

          {!frame && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-white/60">
              {state.guestConnected ? 'Waiting for the first frame…' : 'The guest has left the session.'}
            </div>
          )}
        </div>

        {panel !== 'none' && (
          <aside
            data-testid={`viewer-panel-${panel}`}
            className="absolute bottom-0 right-0 top-0 flex w-[420px] flex-col border-l border-white/10 bg-[#16233a] p-4 text-sm text-white/80"
          >
            {panel === 'terminal' ? (
              <TerminalPanel stream={stream} />
            ) : (
              <FilesPanel stream={stream} />
            )}
          </aside>
        )}

        {notice && (
          <div className="absolute bottom-5 left-1/2 -translate-x-1/2 rounded-lg bg-black/70 px-4 py-2 text-sm text-white">
            {notice}
          </div>
        )}
      </div>
    </div>
  )
}
