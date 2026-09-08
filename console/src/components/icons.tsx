/** Inline icon set - no icon font, no network fetch, so the console renders
 *  identically wherever it is served from. */
import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

function Svg({ children, ...props }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      width={20}
      height={20}
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  )
}

export const SupportIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <circle cx="12" cy="12" r="3.5" />
    <path d="m5.7 5.7 3.8 3.8m5 5 3.8 3.8m0-12.6-3.8 3.8m-5 5-3.8 3.8" />
  </Svg>
)

export const BellIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M18 8a6 6 0 1 0-12 0c0 6-2 7-2 7h16s-2-1-2-7" />
    <path d="M13.7 20a2 2 0 0 1-3.4 0" />
  </Svg>
)

export const PersonIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="3.4" />
    <path d="M5.5 19.5a6.5 6.5 0 0 1 13 0" />
  </Svg>
)

export const SessionIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="8.5" cy="9" r="2.6" />
    <circle cx="16" cy="9.8" r="2.2" />
    <path d="M3.6 18.4a5 5 0 0 1 9.8 0M14 18.4a4.4 4.4 0 0 1 6.4-3.7" />
  </Svg>
)

export const SystemInfoIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4.5" width="18" height="12" rx="1.6" />
    <path d="M8 20h8M12 16.5V20" />
  </Svg>
)

export const HistoryIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1" />
    <path d="M3.5 4.5V9H8" />
    <path d="M12 7.5V12l3 1.8" />
  </Svg>
)

export const ChatIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.5 11.5a7.5 7.5 0 0 1-10.9 6.7L4 19.5l1.4-4.6A7.5 7.5 0 1 1 20.5 11.5Z" />
  </Svg>
)

export const TerminalIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4.5" width="18" height="15" rx="1.8" />
    <path d="m7.5 10 2.5 2-2.5 2M12.5 14.5h4" />
  </Svg>
)

export const FilesIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13.5 3.5H7a1.5 1.5 0 0 0-1.5 1.5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8.5Z" />
    <path d="M13.5 3.5v5h5" />
  </Svg>
)

export const ToolsIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.7 6.3a4 4 0 0 0 5.1 5.1l-8 8a2.4 2.4 0 0 1-3.4-3.4Z" />
    <path d="m6.5 6.5 2 2" />
  </Svg>
)

export const DownloadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4v10" />
    <path d="m8 10.5 4 4 4-4" />
    <path d="M4.5 19.5h15" />
  </Svg>
)

export const LogsIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4" y="3.5" width="16" height="17" rx="1.6" />
    <path d="M8 8h8M8 12h8M8 16h5" />
  </Svg>
)

export const LocateIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="6" />
    <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
  </Svg>
)

export const PencilIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
  </Svg>
)

export const CopyIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="9" width="11" height="11" rx="1.6" />
    <path d="M15 5.5H5.5a1.5 1.5 0 0 0-1.5 1.5V16" />
  </Svg>
)

export const HourglassIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3.5h10M7 20.5h10" />
    <path d="M8 3.5c0 3.4 4 4.9 4 8.5s-4 5.1-4 8.5M16 3.5c0 3.4-4 4.9-4 8.5s4 5.1 4 8.5" />
  </Svg>
)

export const SearchIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="m20 20-4.5-4.5" />
  </Svg>
)

export const CaretIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 9.5 6 5.5 6-5.5" />
  </Svg>
)

export const JoinIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M10 4.5H6A1.5 1.5 0 0 0 4.5 6v12A1.5 1.5 0 0 0 6 19.5h4" />
    <path d="M14 8.5 17.5 12 14 15.5M9 12h8.5" />
  </Svg>
)

export const EditIcon = PencilIcon

export const DeleteIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 6.5h15M9.5 6.5V4.8h5v1.7M6.5 6.5 7.4 20h9.2l.9-13.5" />
  </Svg>
)

export const MoreIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="5.5" cy="12" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
    <circle cx="18.5" cy="12" r="1.3" fill="currentColor" stroke="none" />
  </Svg>
)

export const ScreenshotIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 8.5V6a1.5 1.5 0 0 1 1.5-1.5H8M16 4.5h2.5A1.5 1.5 0 0 1 20 6v2.5M20 15.5V18a1.5 1.5 0 0 1-1.5 1.5H16M8 19.5H5.5A1.5 1.5 0 0 1 4 18v-2.5" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
)

export const MonitorSwitchIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="5" width="12" height="9" rx="1.4" />
    <rect x="9.5" y="10" width="12" height="9" rx="1.4" />
  </Svg>
)

export const ZoomInIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="M11 8.5v5M8.5 11h5M20 20l-4.5-4.5" />
  </Svg>
)

export const ZoomOutIcon = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6" />
    <path d="M8.5 11h5M20 20l-4.5-4.5" />
  </Svg>
)

export const AnnotateIcon = PencilIcon

export const ClearIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 20h11" />
    <path d="M15.5 4.5 20 9 10.5 18.5 5 19l.5-5.5Z" />
  </Svg>
)

export const UploadIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20V10" />
    <path d="m8 13.5 4-4 4 4" />
    <path d="M4.5 4.5h15" />
  </Svg>
)

export const FullscreenIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9V4.5h5M20 9V4.5h-5M4 15v4.5h5M20 15v4.5h-5" />
  </Svg>
)

export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 6 12 12M18 6 6 18" />
  </Svg>
)

export const EyeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
    <circle cx="12" cy="12" r="2.6" />
  </Svg>
)

export const EyeSlashIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.9 5.2A9.7 9.7 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3 3.7M6.4 7.3A17 17 0 0 0 2.5 12S6 19 12 19a9.4 9.4 0 0 0 4-.9" />
    <path d="m3 3 18 18" />
  </Svg>
)

export const PointerIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 3.5 12.5 7.7-5.4 1.3 2.6 5.6-2.3 1.1-2.6-5.6-4.8 2.6Z" />
  </Svg>
)

export const ClipboardIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6" y="4.5" width="12" height="15" rx="1.6" />
    <path d="M9.5 4.5V3.4h5v1.1" />
    <path d="M12 9v6M9.5 12.5 12 15l2.5-2.5" />
  </Svg>
)

export const ClipboardPullIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6" y="4.5" width="12" height="15" rx="1.6" />
    <path d="M9.5 4.5V3.4h5v1.1" />
    <path d="M12 15V9M9.5 11.5 12 9l2.5 2.5" />
  </Svg>
)
