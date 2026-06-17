import type { PatchDiffLine } from '@/types'
import { cn } from '@/lib/utils'

export type GitDiffViewerProps = {
  file: string
  lines: PatchDiffLine[]
  status?: 'pending' | 'applied' | 'rejected'
  onAccept?: () => void
  onReject?: () => void
  busy?: boolean
  className?: string
}

export default function GitDiffViewer({
  file,
  lines,
  status = 'pending',
  onAccept,
  onReject,
  busy = false,
  className,
}: GitDiffViewerProps) {
  return (
    <div
      className={cn(
        'overflow-hidden rounded-lg border border-[#1e1e2e] bg-[#0a0a0f]',
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1e1e2e] bg-[#111118] px-4 py-2">
        <span className="font-mono text-xs text-slate-300">{file}</span>
        {status === 'pending' && onAccept && onReject && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onAccept}
              disabled={busy}
              className="rounded-md bg-emerald-600/90 px-3 py-1 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              Accept Changes
            </button>
            <button
              type="button"
              onClick={onReject}
              disabled={busy}
              className="rounded-md border border-[#1e1e2e] px-3 py-1 text-xs font-medium text-slate-300 hover:bg-[#1e1e2e] disabled:opacity-50"
            >
              Reject Changes
            </button>
          </div>
        )}
        {status !== 'pending' && (
          <span
            className={cn(
              'text-xs font-medium uppercase',
              status === 'applied' ? 'text-emerald-400' : 'text-red-400',
            )}
          >
            {status}
          </span>
        )}
      </div>

      <pre className="overflow-x-auto p-0 text-xs leading-5">
        {lines.map((line, i) => (
          <div
            key={`${line.lineNumber}-${i}`}
            className={cn(
              'flex font-mono',
              line.type === 'add' && 'bg-green-950/30 text-green-400',
              line.type === 'remove' && 'bg-red-950/30 text-red-400',
              line.type === 'context' && 'text-slate-500',
            )}
          >
            <span className="w-10 shrink-0 select-none border-r border-[#1e1e2e] px-2 text-right text-slate-600">
              {line.lineNumber}
            </span>
            <span className="w-6 shrink-0 select-none text-center">
              {line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' '}
            </span>
            <span className="flex-1 whitespace-pre px-2">{line.content}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}
