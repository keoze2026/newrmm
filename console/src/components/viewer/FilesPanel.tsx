import { useCallback, useEffect, useRef, useState } from 'react'
import type { SessionStream } from '../../lib/stream'

interface Entry {
  name: string
  dir: boolean
  size: number
  modified: number
}

const CHUNK = 256 * 1024

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Browse, send and retrieve files on the endpoint (Appendix A.7). */
export default function FilesPanel({ stream }: { stream: SessionStream }) {
  const [path, setPath] = useState<string>('')
  const [parent, setParent] = useState<string | null>(null)
  const [entries, setEntries] = useState<Entry[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const download = useRef<{ name: string; parts: string[] } | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const list = useCallback((next?: string) => {
    stream.send({ type: 'files', action: 'list', path: next })
  }, [stream])

  useEffect(() => {
    const unsubscribe = stream.subscribe((message) => {
      if (message.type !== 'files') return

      if (message.action === 'list') {
        setPath(String(message.path ?? ''))
        setParent((message.parent as string) ?? null)
        setEntries((message.entries as Entry[]) ?? [])
        setError((message.error as string) ?? null)
      } else if (message.action === 'chunk') {
        const name = String(message.name ?? 'download')
        if (!download.current || download.current.name !== name) {
          download.current = { name, parts: [] }
        }
        download.current.parts.push(String(message.data ?? ''))
        if (message.final) {
          const binary = atob(download.current.parts.join(''))
          const bytes = new Uint8Array(binary.length)
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
          const url = URL.createObjectURL(new Blob([bytes]))
          const link = document.createElement('a')
          link.href = url
          link.download = name
          link.click()
          URL.revokeObjectURL(url)
          download.current = null
          setBusy(null)
        }
      } else if (message.action === 'received') {
        setBusy(null)
        list(path)
      } else if (message.action === 'error') {
        setError(String(message.error ?? 'Something went wrong'))
        setBusy(null)
      }
    })
    list()
    return unsubscribe
  }, [stream, list, path])

  async function send(file: File) {
    setBusy(`Sending ${file.name}…`)
    const target = `${path}/${file.name}`
    const buffer = new Uint8Array(await file.arrayBuffer())
    for (let offset = 0; offset < buffer.length || offset === 0; offset += CHUNK) {
      const slice = buffer.subarray(offset, offset + CHUNK)
      let binary = ''
      slice.forEach((byte) => {
        binary += String.fromCharCode(byte)
      })
      stream.send({
        type: 'files',
        action: 'put',
        path: target,
        data: btoa(binary),
        final: offset + CHUNK >= buffer.length,
      })
      if (buffer.length === 0) break
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-1 pb-2">
        <h3 className="text-sm font-semibold text-white">Files</h3>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="rounded-md border border-white/15 px-2 py-1 text-[11px] text-white/80 hover:bg-white/10"
          >
            Send file
          </button>
          <input
            ref={fileInput}
            type="file"
            data-testid="files-upload"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) send(file)
              e.target.value = ''
            }}
          />
        </div>
      </div>

      <div className="mb-2 truncate font-mono text-[11px] text-white/45" title={path}>
        {path || '…'}
      </div>

      {error && (
        <div className="mb-2 rounded-md bg-red-500/15 px-2.5 py-1.5 text-[11px] text-red-200">
          {error}
        </div>
      )}
      {busy && (
        <div className="mb-2 rounded-md bg-white/10 px-2.5 py-1.5 text-[11px] text-white/80">
          {busy}
        </div>
      )}

      <ul
        data-testid="files-list"
        className="min-h-0 flex-1 overflow-auto rounded-md border border-white/10 bg-black/25 text-[12px]"
      >
        {parent && (
          <li>
            <button
              type="button"
              onClick={() => list(parent)}
              className="block w-full px-3 py-1.5 text-left font-mono text-white/60 hover:bg-white/10"
            >
              ../
            </button>
          </li>
        )}
        {entries.map((entry) => (
          <li key={entry.name} className="flex items-center gap-2 px-3 py-1.5 hover:bg-white/10">
            <button
              type="button"
              onClick={() => {
                if (entry.dir) {
                  list(`${path}/${entry.name}`)
                } else {
                  setBusy(`Retrieving ${entry.name}…`)
                  stream.send({ type: 'files', action: 'get', path: `${path}/${entry.name}` })
                }
              }}
              className="min-w-0 flex-1 truncate text-left font-mono text-white/85"
              title={entry.name}
            >
              {entry.dir ? '📁 ' : ''}
              {entry.name}
            </button>
            <span className="shrink-0 font-mono text-[11px] text-white/35">
              {entry.dir ? '' : formatSize(entry.size)}
            </span>
          </li>
        ))}
        {entries.length === 0 && !error && (
          <li className="px-3 py-3 text-white/40">This folder is empty.</li>
        )}
      </ul>
    </div>
  )
}
