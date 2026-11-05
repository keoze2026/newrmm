import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import type { SessionStream } from '../../lib/stream'

/** A shell on the endpoint, inside the viewer (Appendix A.7).
 *
 * A real terminal emulator (xterm.js), not a line-buffered input box feeding
 * a colour-only text renderer: the previous version sent a whole line at a
 * time on Enter and only interpreted ANSI colour codes, appending output as
 * plain growing text. Interactive full-screen programs (vim, top, htop, less)
 * need every keystroke the instant it is typed - not buffered until Enter -
 * and need the escape sequences that move the cursor and redraw regions of
 * the screen actually obeyed, not stripped down to colour. The agent's own
 * side (`terminal.py`) already passed raw bytes straight through a real pty
 * on Linux/macOS and already supported a `resize` message
 * (`session.py`'s `_handle_terminal`) - neither needed to change; only the
 * console ever fell short of what the protocol already carried.
 */
export default function TerminalPanel({ stream }: { stream: SessionStream }) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 12,
      scrollback: 5000,
      theme: {
        background: '#0a0e16',
        foreground: '#e5e7eb',
      },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(container)
    fit.fit()

    const unsubscribe = stream.subscribe((message) => {
      if (message.type !== 'terminal') return
      if (message.action === 'opened') {
        term.writeln(`\x1b[2m[connected: ${String(message.shell ?? 'shell')}]\x1b[0m`)
      } else if (message.action === 'closed') {
        term.writeln('\r\n\x1b[2m[the shell closed]\x1b[0m')
      } else if (message.action === 'output') {
        term.write(String(message.data ?? ''))
      }
    })

    // Every keystroke goes straight to the shell the instant it is typed -
    // not buffered into a line - which is what distinguishes a real terminal
    // from a command box and is required for vim, top and anything else that
    // reads single keys (arrow keys, Ctrl+C, i/Esc, etc.) directly.
    const onData = term.onData((data) => {
      stream.send({ type: 'terminal', action: 'input', data })
    })
    const onResize = term.onResize(({ cols, rows }) => {
      stream.send({ type: 'terminal', action: 'resize', cols, rows })
    })

    stream.send({ type: 'terminal', action: 'open', cols: term.cols, rows: term.rows })
    term.focus()

    // The viewer panel can resize (window resize, switching panels); the
    // terminal grid - and the shell's own idea of its window size - must
    // track it, or output wraps at the wrong column and full-screen programs
    // misdraw.
    const resizeObserver = new ResizeObserver(() => fit.fit())
    resizeObserver.observe(container)

    // The shell belongs to the session, not to this panel: switching to
    // Files and back must not kill it. The viewer closes it on exit; this
    // only tears down the local terminal UI and listeners.
    return () => {
      unsubscribe()
      onData.dispose()
      onResize.dispose()
      resizeObserver.disconnect()
      term.dispose()
    }
  }, [stream])

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <h3 className="text-sm font-semibold text-white">Terminal</h3>
      </div>
      <div
        ref={containerRef}
        data-testid="terminal-output"
        className="min-h-0 flex-1 overflow-hidden rounded-md bg-black/40 p-2"
      />
    </div>
  )
}
