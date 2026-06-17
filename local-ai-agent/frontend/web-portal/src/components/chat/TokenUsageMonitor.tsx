import { cn } from '@/lib/utils'

export type TokenUsageMonitorProps = {
  used: number
  max?: number
  className?: string
}

export default function TokenUsageMonitor({
  used,
  max = 32_768,
  className,
}: TokenUsageMonitorProps) {
  const pct = Math.min(100, (used / max) * 100)

  return (
    <div className={cn('min-w-[200px]', className)}>
      <div className="flex items-center justify-between font-mono text-[10px] text-slate-500">
        <span>Context window</span>
        <span>
          {used.toLocaleString()} / {max.toLocaleString()} tokens
        </span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-[#1e1e2e]">
        <div
          className="h-full rounded-full bg-[#7c3aed] transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
