import type { SourceCitation } from '../types'

type SourceCitationListProps = {
  sources: SourceCitation[]
}

export default function SourceCitationList({ sources }: SourceCitationListProps) {
  if (sources.length === 0) return null

  return (
    <div className="mt-3 space-y-2">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Sources
      </p>
      {sources.map((src, i) => (
        <div
          key={`${src.file}-${src.lineStart}-${i}`}
          className="rounded-lg border border-slate-700 bg-slate-900/80 p-3"
        >
          <p className="font-mono text-xs text-violet-300">
            {src.file}:{src.lineStart}
            {src.lineEnd !== src.lineStart ? `–${src.lineEnd}` : ''}
          </p>
          <pre className="mt-2 overflow-x-auto font-mono text-xs text-slate-400">
            {src.snippet}
          </pre>
        </div>
      ))}
    </div>
  )
}
