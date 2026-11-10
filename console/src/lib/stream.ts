/** Live session stream: receives guest screen frames and sends operator input.
 *
 *  Frames arrive as binary JPEG and are decoded to ImageBitmap off the main
 *  thread. Input is sent with normalised 0..1 coordinates so the guest maps a
 *  click to the same point regardless of how the canvas is letterboxed.
 */
import { FrameAssembler } from './frames'
import { operatorAuthMessage, operatorSocketUrl, type Monitor, type SystemInfo } from './api'

export interface StreamStats {
  fps: number
  kbps: number
}

/** What the endpoint can actually do when asked to blank its screen. */
export type PrivacyMode = 'capture-excluded' | 'guest-lock' | 'unavailable' | null

export interface StreamState {
  connected: boolean
  guestConnected: boolean
  hostName: string | null
  systemInfo: SystemInfo
  monitors: Monitor[]
  stats: StreamStats
  privacyMode: PrivacyMode
  blanked: boolean
}

export type FrameSource = HTMLCanvasElement | OffscreenCanvas
export type FrameHandler = (frame: FrameSource) => void
export type StateHandler = (state: StreamState) => void
export type MessageHandler = (message: Record<string, unknown>) => void

// Liveness watchdog - recovers a frozen viewer as fast as possible without
// firing on a healthy idle screen. The endpoint sends a frame every tick even
// when nothing changed (a zero-tile frame), so while frames keep ARRIVING the
// stream is alive and an idle screen is not a fault. The true freeze signal is
// frames stopping entirely: no frame for STALE_MS -> ask the endpoint for a
// fresh one (like a manual refresh); still nothing PROBE_GRACE_MS later ->
// rebuild the socket at once, no backoff. (Watching the pixels alone instead
// would request a keyframe every second on a genuinely still screen, because a
// zero-tile frame never repaints - so this keys on frames arriving, which is
// the same freeze signal without that waste. The agent restarts a genuinely
// stalled capture itself, so "frames arriving" reliably means "not frozen".)
const STALE_MS = 1000
const PROBE_GRACE_MS = 1000
const LIVENESS_CHECK_MS = 250

export interface InputMessage {
  type: 'input'
  kind: 'mouse' | 'key' | 'scroll'
  action?: 'move' | 'down' | 'up' | 'click'
  x?: number
  y?: number
  button?: 'left' | 'right' | 'middle'
  key?: string
  text?: string
  dx?: number
  dy?: number
  modifiers?: string[]
}

export type ControlMessage =
  | InputMessage
  | { type: 'monitor'; index: number }
  | { type: 'blank'; on: boolean }
  | { type: 'quality'; level: number }
  | { type: 'terminal'; action: 'open' | 'input' | 'resize' | 'close'; data?: string; cols?: number; rows?: number }
  | { type: 'files'; action: 'list' | 'get' | 'put'; path?: string; data?: string; final?: boolean }
  | { type: 'clipboard'; action: 'get' | 'set'; text?: string }
  | { type: 'chat'; action: 'message'; text: string }
  | { type: 'keyframe' }
  | { type: 'end' }

export class SessionStream {
  private socket: WebSocket | null = null
  private frameTimes: number[] = []
  private bytesWindow: { at: number; bytes: number }[] = []
  private statsTimer: number | null = null
  private reconnectTimer: number | null = null
  private livenessTimer: number | null = null
  private lastFrameAt = 0
  // When we last asked for a fresh frame because frames stopped; 0 = not asked.
  private probedAt = 0
  private closed = false
  private listeners = new Set<MessageHandler>()
  private assembler = new FrameAssembler()

  state: StreamState = {
    connected: false,
    guestConnected: false,
    hostName: null,
    systemInfo: {},
    monitors: [],
    stats: { fps: 0, kbps: 0 },
    privacyMode: null,
    blanked: false,
  }

  constructor(
    private code: string,
    private onFrame: FrameHandler,
    private onState: StateHandler,
  ) {}

  connect() {
    this.closed = false
    // A reconnect still pending from a previous drop must not also fire once
    // this fresh connect() is already under way - without this, close()
    // could not actually cancel it (see close() below), and a stream the app
    // believes is dead could silently resurrect itself moments later and
    // start overwriting UI state for a session the operator already left.
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    const socket = new WebSocket(operatorSocketUrl(this.code))
    socket.binaryType = 'arraybuffer'
    this.socket = socket

    socket.onopen = () => {
      // Authenticate before anything else; the relay reads this first.
      socket.send(operatorAuthMessage())
      // A reconnect starts a new picture: the old one cannot be patched.
      this.assembler.reset()
      // Fresh grace window for the watchdog: a just-opened socket has had no
      // time to deliver a frame yet, and the relay is about to ask the guest
      // for a keyframe.
      this.lastFrameAt = performance.now()
      this.probedAt = 0
      this.state = { ...this.state, connected: true }
      this.onState(this.state)
    }

    socket.onmessage = async (event) => {
      if (typeof event.data === 'string') {
        const message = JSON.parse(event.data)
        this.handleControl(message)
        // Tool replies - terminal output, file chunks, clipboard - go to
        // whichever panel is listening.
        this.listeners.forEach((listener) => listener(message))
        return
      }
      const buffer = event.data as ArrayBuffer
      this.recordFrame(buffer.byteLength)
      try {
        const frame = await this.assembler.apply(buffer)
        // A tile update that arrives before the first whole frame has nothing
        // to patch, so it is skipped; the relay has already asked for one.
        if (frame && frame.tiles > 0) this.onFrame(frame.canvas)
      } catch {
        /* a damaged message is dropped; the next keyframe repairs it */
      }
    }

    socket.onclose = () => {
      this.state = { ...this.state, connected: false }
      this.onState(this.state)
      // Reconnect unless the operator closed the viewer (spec section 8:
      // "reconnects automatically after drops"). The handle is stored so
      // close() can actually cancel it - previously it could not, and a
      // reconnect scheduled just before close() would still fire afterward.
      if (!this.closed) {
        this.reconnectTimer = window.setTimeout(() => this.connect(), 1500)
      }
    }

    // Each reconnect used to start a new interval without ever clearing the
    // previous one - close() can only ever clear the single most recent
    // handle, so every earlier reconnect on a flaky connection leaked its own
    // setInterval, forever, each one still calling publishStats()/onState()
    // every 500ms for the life of the page.
    if (this.statsTimer !== null) window.clearInterval(this.statsTimer)
    this.statsTimer = window.setInterval(() => this.publishStats(), 500)

    // Same leak reasoning as statsTimer: clear any previous one before starting
    // a fresh watchdog on a reconnect.
    if (this.livenessTimer !== null) window.clearInterval(this.livenessTimer)
    this.livenessTimer = window.setInterval(() => this.checkLiveness(), LIVENESS_CHECK_MS)
  }

  private handleControl(message: Record<string, unknown>) {
    const type = message.type as string
    if (type === 'attached' || type === 'guest_joined') {
      const info = (message.system_info as SystemInfo) ?? this.state.systemInfo
      this.state = {
        ...this.state,
        guestConnected: type === 'guest_joined' ? true : Boolean(message.guest_connected),
        hostName: (message.host_name as string) ?? this.state.hostName,
        systemInfo: info,
        monitors: (message.monitors as Monitor[]) ?? this.state.monitors,
        privacyMode: (message.privacy_mode as PrivacyMode) ?? this.state.privacyMode,
      }
      // The guest just started sharing: give the watchdog a fresh window for
      // the first frame to arrive before it can consider the stream stale.
      if (this.state.guestConnected) {
        this.lastFrameAt = performance.now()
        this.probedAt = 0
      }
      this.onState(this.state)
    } else if (type === 'guest_left') {
      this.state = { ...this.state, guestConnected: false, blanked: false }
      this.onState(this.state)
    } else if (type === 'blank' && message.action === 'state') {
      this.state = {
        ...this.state,
        blanked: Boolean(message.active),
        privacyMode: (message.mode as PrivacyMode) ?? this.state.privacyMode,
      }
      this.onState(this.state)
    }
  }

  private recordFrame(bytes: number) {
    const now = performance.now()
    this.lastFrameAt = now
    this.frameTimes.push(now)
    this.bytesWindow.push({ at: now, bytes })
  }

  private checkLiveness() {
    if (this.closed) return
    if (this.socket?.readyState !== WebSocket.OPEN) return
    // Frames are only expected once the guest has consented and is sharing;
    // before that, a quiet socket is normal and must not trigger anything.
    if (!this.state.guestConnected) return
    const since = performance.now() - this.lastFrameAt
    if (since < STALE_MS) {
      this.probedAt = 0
      return
    }
    // Frames have stopped. First ask the endpoint for a fresh frame - cheap,
    // and enough if the stream is only momentarily behind. Only if that brings
    // nothing back do we rebuild the socket.
    if (this.probedAt === 0) {
      console.info('[viewer] no frames for %dms - requesting a fresh frame', Math.round(since))
      this.send({ type: 'keyframe' })
      this.probedAt = performance.now()
      return
    }
    if (performance.now() - this.probedAt >= PROBE_GRACE_MS) {
      console.info('[viewer] still no frames after a keyframe request - rebuilding the connection')
      this.forceReconnect()
    }
  }

  /** The socket looks open but has gone silent: tear it down and reconnect at
   *  once, so the viewer recovers on its own instead of staying frozen. */
  private forceReconnect() {
    const socket = this.socket
    if (socket) {
      // Detach handlers first: this socket's own onclose must not also schedule
      // the slower 1.5s reconnect - connect() below reconnects immediately.
      socket.onopen = null
      socket.onmessage = null
      socket.onerror = null
      socket.onclose = null
      try {
        socket.close()
      } catch {
        /* already gone */
      }
    }
    this.socket = null
    this.probedAt = 0
    this.state = { ...this.state, connected: false }
    this.onState(this.state)
    this.connect()
  }

  private publishStats() {
    const now = performance.now()
    const cutoff = now - 1000
    this.frameTimes = this.frameTimes.filter((t) => t >= cutoff)
    this.bytesWindow = this.bytesWindow.filter((b) => b.at >= cutoff)
    const bytes = this.bytesWindow.reduce((sum, b) => sum + b.bytes, 0)
    const stats = { fps: this.frameTimes.length, kbps: Math.round((bytes * 8) / 1000) }
    this.state = { ...this.state, stats }
    this.onState(this.state)
  }

  /** Listen for JSON messages from the endpoint. Returns an unsubscribe. */
  subscribe(listener: MessageHandler): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  /** Sends if the socket is open right now; returns whether it actually did,
   * so a caller doing a multi-part transfer (a file upload) can tell a drop
   * mid-transfer apart from a message that genuinely went out. */
  send(message: ControlMessage): boolean {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(message))
      return true
    }
    return false
  }

  close() {
    this.closed = true
    if (this.statsTimer !== null) window.clearInterval(this.statsTimer)
    if (this.livenessTimer !== null) window.clearInterval(this.livenessTimer)
    if (this.reconnectTimer !== null) window.clearTimeout(this.reconnectTimer)
    this.socket?.close()
    this.socket = null
    this.listeners.clear()
  }
}
