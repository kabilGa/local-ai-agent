export default function LocalModelBadge() {
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-[#1e1e2e] bg-[#111118] px-3 py-1.5 font-mono text-xs tracking-wide text-slate-300">
      <span className="relative flex h-2 w-2">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
      </span>
      LOCAL // qwen2.5-coder:3b
    </div>
  )
}

export { LocalModelBadge }
