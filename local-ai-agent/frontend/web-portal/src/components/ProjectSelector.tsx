import { useProject } from '../context/ProjectContext'
import type { ExplainMode } from '../types'

const MODES: { value: ExplainMode; label: string }[] = [
  { value: 'novice', label: 'Novice' },
  { value: 'standard', label: 'Standard' },
  { value: 'expert', label: 'Expert' },
]

export default function ProjectSelector() {
  const {
    projects,
    selectedProject,
    explainMode,
    setSelectedProjectId,
    setExplainMode,
    isLoading,
  } = useProject()

  if (isLoading) {
    return <p className="text-sm text-slate-500">Loading projects…</p>
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-2 text-sm text-slate-400">
        Project
        <select
          value={selectedProject?.id ?? ''}
          onChange={(e) => setSelectedProjectId(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-violet-500"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name} ({p.branch})
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-sm text-slate-400">
        Explain mode
        <select
          value={explainMode}
          onChange={(e) => setExplainMode(e.target.value as ExplainMode)}
          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-100 outline-none focus:border-violet-500"
        >
          {MODES.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
