import {
  ChatIcon,
  DownloadIcon,
  FilesIcon,
  HistoryIcon,
  LocateIcon,
  LogsIcon,
  SessionIcon,
  SystemInfoIcon,
  TerminalIcon,
  ToolsIcon,
} from './icons'

export type TabKey =
  | 'session'
  | 'system'
  | 'history'
  | 'chat'
  | 'terminal'
  | 'files'
  | 'tools'
  | 'download'
  | 'logs'
  | 'locate'

/** Order is fixed by Appendix A.4, top to bottom. */
export const TABS: { key: TabKey; label: string; Icon: typeof SessionIcon }[] = [
  { key: 'session', label: 'Session', Icon: SessionIcon },
  { key: 'system', label: 'System info', Icon: SystemInfoIcon },
  { key: 'history', label: 'Session history', Icon: HistoryIcon },
  { key: 'chat', label: 'Chat', Icon: ChatIcon },
  { key: 'terminal', label: 'Terminal', Icon: TerminalIcon },
  { key: 'files', label: 'Files', Icon: FilesIcon },
  { key: 'tools', label: 'Tools', Icon: ToolsIcon },
  { key: 'download', label: 'Download', Icon: DownloadIcon },
  { key: 'logs', label: 'Logs', Icon: LogsIcon },
  { key: 'locate', label: 'Locate', Icon: LocateIcon },
]

export default function TabStrip({
  active,
  onChange,
}: {
  active: TabKey
  onChange: (key: TabKey) => void
}) {
  return (
    <div className="flex w-[54px] shrink-0 flex-col border-r border-line bg-white py-2">
      {TABS.map(({ key, label, Icon }) => {
        const isActive = key === active
        return (
          <button
            key={key}
            type="button"
            title={label}
            aria-label={label}
            aria-current={isActive ? 'true' : undefined}
            data-testid={`tab-${key}`}
            data-active={isActive}
            onClick={() => onChange(key)}
            className={`flex h-11 items-center justify-center border-l-[3px] transition ${
              isActive
                ? 'border-primary bg-primary-soft text-primary'
                : 'border-transparent text-muted hover:bg-canvas hover:text-navy'
            }`}
          >
            <Icon width={20} height={20} />
          </button>
        )
      })}
    </div>
  )
}
