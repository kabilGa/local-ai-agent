import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export type FileContextBarProps = {
  files: string[]
  onRemove: (file: string) => void
  className?: string
}

export default function FileContextBar({
  files,
  onRemove,
  className,
}: FileContextBarProps) {
  if (files.length === 0) return null

  return (
    <div
      className={cn(
        'flex flex-wrap gap-2 border-b border-[#1e1e2e] bg-[#0a0a0f] px-1 py-2',
        className,
      )}
    >
      {files.map((file) => (
        <button
          key={file}
          type="button"
          onClick={() => onRemove(file)}
          className="inline-flex items-center gap-1.5 rounded-full border border-[#1e1e2e] bg-[#111118] px-2.5 py-1 font-mono text-xs text-slate-300 transition-colors hover:border-[#7c3aed]/50 hover:text-white"
        >
          <X className="h-3 w-3 text-slate-500" />
          {file}
        </button>
      ))}
    </div>
  )
}
