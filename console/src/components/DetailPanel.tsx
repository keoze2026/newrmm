import TabStrip, { type TabKey } from './TabStrip'
import SessionTab from './tabs/SessionTab'
import {
  HistoryTab,
  LaunchTab,
  LogsTab,
  NotImplementedTab,
  SystemInfoTab,
} from './tabs/OtherTabs'
import type { Session } from '../lib/api'
import type { FrameSource } from '../lib/stream'

/** Column 4 (Appendix A.2, A.4-A.6). */
export default function DetailPanel({
  session,
  tab,
  onTab,
  onRename,
  onJoin,
  previewBitmap,
  previewSeq,
  editRequest,
}: {
  session: Session | null
  tab: TabKey
  onTab: (key: TabKey) => void
  onRename: (name: string) => Promise<void>
  onJoin: () => void
  previewBitmap: FrameSource | null
  previewSeq: number
  editRequest: number
}) {
  if (!session) {
    return (
      <section className="flex flex-1 items-center justify-center bg-canvas">
        <p className="text-sm text-muted">Select a session to see its details.</p>
      </section>
    )
  }

  return (
    <section className="flex flex-1 overflow-hidden bg-canvas">
      <TabStrip active={tab} onChange={onTab} />
      <div className="flex-1 overflow-y-auto">
        {tab === 'session' && (
          <SessionTab
            session={session}
            onRename={onRename}
            onJoin={onJoin}
            previewBitmap={previewBitmap}
            previewSeq={previewSeq}
            editRequest={editRequest}
          />
        )}
        {tab === 'system' && <SystemInfoTab session={session} />}
        {tab === 'history' && <HistoryTab session={session} />}
        {tab === 'logs' && <LogsTab session={session} />}
        {tab === 'terminal' && (
          <LaunchTab
            title="Terminal"
            session={session}
            onJoin={onJoin}
            description="Open a shell on the endpoint inside the session viewer."
          />
        )}
        {tab === 'files' && (
          <LaunchTab
            title="Files"
            session={session}
            onJoin={onJoin}
            description="Browse, send and retrieve files on the endpoint inside the session viewer."
          />
        )}
        {tab === 'download' && (
          <LaunchTab
            title="Download"
            session={session}
            onJoin={onJoin}
            description="Retrieve files from the endpoint inside the session viewer."
          />
        )}
        {tab === 'chat' && (
          <NotImplementedTab
            title="Chat"
            note="In-session chat with the guest is not built yet."
          />
        )}
        {tab === 'tools' && (
          <NotImplementedTab
            title="Tools"
            note="Endpoint utilities beyond the terminal and file browser are not built yet."
          />
        )}
        {tab === 'locate' && (
          <NotImplementedTab
            title="Locate"
            note="Locating the endpoint on a map is not built yet."
          />
        )}
      </div>
    </section>
  )
}
