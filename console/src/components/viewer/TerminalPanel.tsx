import { useEffect, useMemo, useRef, useState } from 'react'
import { applyControlChars, parseAnsi } from '../../lib/ansi'
import type { SessionStream } from '../../lib/stream'

/** A shell on the endpoint, inside the viewer (Appendix A.7). */
export default function TerminalPanel({ stream }: { stream: SessionStream }) {
  const [lines, setLines] = useState('')
  const [shell, setShell] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const outputRef = useRef<HTMLPreElement>(null)
  const rendered = useMemo(() => parseAnsi(applyControlChars(lines)), [lines])
  const inputRef = useRef<HTMLInputElement>(null)
  const history = useRef<string[]>([])
  const historyAt = useRef<number>(-1)

  useEffect(() => {
    const unsubscribe = stream.subscribe((message) => {
      if (message.type !== 'terminal') return
      if (message.action === 'opened') setShell(String(message.shell ?? 'shell'))
      if (message.action === 'closed') setShell(null)
      if (message.action === 'output') setLines((prev) => (prev + String(message.data ?? '')).slice(-200_000))
    })
    stream.send({ type: 'terminal', action: 'open', cols: 100, rows: 30 })
    inputRef.current?.focus()
    // The shell belongs to the session, not to this panel: switching to Files
    // and back must not kill it. The viewer closes it on exit.
    return unsubscribe
  }, [stream])

  useEffect(() => {
    const node = outputRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [lines])

  function submit() {
    stream.send({ type: 'terminal', action: 'input', data: draft + '\n' })
    if (draft.trim()) {
      history.current.push(draft)
      historyAt.current = history.current.length
    }
    setDraft('')
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <h3 className="text-sm font-semibold text-white">Terminal</h3>
        <span className="font-mono text-[11px] text-white/45">{shell ?? 'connecting…'}</span>
      </div>

      <pre
        ref={outputRef}
        data-testid="terminal-output"
        className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/40 p-3 font-mono text-[12px] leading-relaxed text-white/85"
      >
        {rendered.map((segment, i) => (
          <span
            key={i}
            style={{
              color: segment.colour,
              fontWeight: segment.bold ? 600 : undefined,
              opacity: segment.dim ? 0.65 : undefined,
            }}
          >
            {segment.text}
          </span>
        ))}
      </pre>

      <div className="mt-2 flex items-center gap-2">
        <span className="font-mono text-sm text-white/40">$</span>
        <input
          ref={inputRef}
          value={draft}
          data-testid="terminal-input"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            // The viewer sends keystrokes to the guest's screen; while the
            // terminal has focus they belong to the shell instead.
            e.stopPropagation()
            if (e.key === 'Enter') {
              submit()
            } else if (e.key === 'ArrowUp') {
              e.preventDefault()
              historyAt.current = Math.max(0, historyAt.current - 1)
              setDraft(history.current[historyAt.current] ?? '')
            } else if (e.key === 'ArrowDown') {
              e.preventDefault()
              historyAt.current = Math.min(history.current.length, historyAt.current + 1)
              setDraft(history.current[historyAt.current] ?? '')
            } else if (e.key === 'c' && e.ctrlKey) {
              stream.send({ type: 'terminal', action: 'input', data: '\x03' })
            }
          }}
          placeholder="Type a command and press Enter"
          className="flex-1 rounded-md border border-white/15 bg-black/40 px-2.5 py-1.5 font-mono text-[12px] text-white outline-none focus:border-primary"
        />
      </div>
    </div>
  )
}
