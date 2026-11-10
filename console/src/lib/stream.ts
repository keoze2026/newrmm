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

// Dead-link watchdog. A browser WebSocket exposes no ping/pong and fires no
// onclose on a half-open TCP link (NAT/wifi-roam/sleep, or a proxy dropping one
// direction), so a frozen viewer would otherwise sit at readyState OPEN for
// ever while nothing arrives. The relay now sends a heartbeat ping every second,
// so a healthy socket is NEVER silent - frames when the screen moves, a ping
// when it is idle. So the dead-link signal is simply: no message of ANY kind
// (frame or ping) for DEAD_LINK_MS -> the link is dead; close it and reconnect
// at once (the relay asks the guest for a fresh keyframe on the new socket).
// Deliberately NOT based on the picture changing or on frame bytes: an idle
// screen legitimately sends no frames, but the heartbeat still arrives, so the
// link is proven alive without a single repaint.
const DEAD_LINK_MS = 3000
const LIVENESS_CHECK_MS = 500

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
  // When the last message of ANY kind (a frame or the relay's heartbeat ping)
  // arrived. The dead-link watchdog keys on this and nothing else.
  private lastMessageAt = 0
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
      // time to deliver anything yet, and the relay is about to ask the guest
      // for a keyframe and start its heartbeat.
      this.lastMessageAt = performance.now()
      this.state = { ...this.state, connected: true }
      this.onState(this.state)
    }

    socket.onmessage = async (event) => {
      // Any message - a frame OR the relay's heartbeat ping - proves the link
      // is alive. The dead-link watchdog keys on this stamp, nothing else.
      this.lastMessageAt = performance.now()
      if (typeof event.data === 'string') {
        const message = JSON.parse(event.data)
        // The heartbeat carries no payload beyond keeping the link audible;
        // it has already done its job above.
        if (message.type === 'ping') return
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
      // The guest just started sharing: give the watchdog a fresh window
      // before it can consider the link dead.
      if (this.state.guestConnected) {
        this.lastMessageAt = performance.now()
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
    this.frameTimes.push(now)
    this.bytesWindow.push({ at: now, bytes })
  }

  private checkLiveness() {
    if (this.closed) return
    if (this.socket?.readyState !== WebSocket.OPEN) return
    // Messages are only expected once the guest has consented and is sharing;
    // before that, a quiet socket is normal and must not trigger anything.
    if (!this.state.guestConnected) return
    // A healthy socket hears from the relay at least once a second (a frame, or
    // a heartbeat ping on an idle screen). Silence this long means a half-open
    // link the browser cannot otherwise detect: tear it down and reconnect.
    const silent = performance.now() - this.lastMessageAt
    if (silent >= DEAD_LINK_MS) {
      console.info(
        '[viewer] no message (frame or heartbeat) for %dms - treating the link as dead and reconnecting',
        Math.round(silent),
      )
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
