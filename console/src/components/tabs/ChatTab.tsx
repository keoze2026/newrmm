import { useEffect, useRef, useState } from 'react'
import { SendIcon } from '../icons'
import type { Session } from '../../lib/api'
import type { SessionStream } from '../../lib/stream'

interface ChatEntry {
  id: number
  from: 'operator' | 'guest'
  text: string
}

let nextId = 1

/** In-session chat (Appendix A tab 'chat'): sends/receives the same
 *  `{type: 'chat', action: 'message', text}` message the agent already
 *  handles (agent/rmm_agent/session.py `_handle_chat`) - no relay changes. */
export default function ChatTab({
  session,
  stream,
  guestConnected,
}: {
  session: Session
  stream: SessionStream | null
  guestConnected: boolean
}) {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setEntries([])
    setDraft('')
  }, [session.id])

  useEffect(() => {
    if (!stream) return
    return stream.subscribe((message) => {
      if (message.type !== 'chat' || message.action !== 'message') return
      const text = String(message.text ?? '').trim()
      if (!text) return
      setEntries((prev) => [...prev, { id: nextId++, from: 'guest', text }])
    })
  }, [stream])

  useEffect(() => {
    const node = listRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [entries])

  function send() {
    const text = draft.trim()
    if (!text || !stream) return
    if (!stream.send({ type: 'chat', action: 'message', text })) return
    setEntries((prev) => [...prev, { id: nextId++, from: 'operator', text }])
    setDraft('')
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-[640px] flex-col px-8 py-8">
      <h2 className="text-lg font-semibold text-navy">Chat</h2>

      <div
        ref={listRef}
        data-testid="chat-history"
        className="mt-5 flex-1 overflow-y-auto rounded-2xl border border-line bg-white p-4 shadow-sm"
      >
        {entries.length === 0 ? (
          <p className="text-sm text-muted">
            {guestConnected
              ? 'Send a message - it opens a chat window on their screen.'
              : 'Chat is available once your guest joins.'}
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className={`max-w-[80%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-sm ${
                  entry.from === 'operator'
                    ? 'self-end bg-gradient-to-b from-primary to-primary-dark text-white'
                    : 'self-start bg-canvas text-navy'
                }`}
              >
                {entry.text}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') send()
          }}
          disabled={!guestConnected}
          placeholder={guestConnected ? 'Type a message…' : 'Waiting for your guest to join…'}
          aria-label="Chat message"
          data-testid="chat-input"
          className="flex-1 rounded-full border border-line-strong bg-white px-4 py-2.5 text-sm text-navy outline-none transition focus:shadow-[0_0_0_4px_rgba(47,111,228,0.12)] disabled:bg-canvas disabled:text-muted"
        />
        <button
          type="button"
          onClick={send}
          disabled={!guestConnected || !draft.trim()}
          data-testid="chat-send"
          title="Send"
          aria-label="Send message"
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-primary to-primary-dark text-white shadow-[0_2px_8px_rgba(47,111,228,0.3)] transition hover:shadow-[0_4px_14px_rgba(47,111,228,0.4)] active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
        >
          <SendIcon width={17} height={17} />
        </button>
      </div>
    </div>
  )
}
