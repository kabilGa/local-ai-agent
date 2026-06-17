import { useEffect, useState } from 'react'
import { getReports } from '../api/reports'
import type { Report } from '../types'

const typeColors: Record<Report['type'], string> = {
  security: 'bg-red-950/50 text-red-300 border-red-800',
  audit: 'bg-blue-950/50 text-blue-300 border-blue-800',
  patch: 'bg-violet-950/50 text-violet-300 border-violet-800',
  indexing: 'bg-emerald-950/50 text-emerald-300 border-emerald-800',
}

const severityColors: Record<NonNullable<Report['severity']>, string> = {
  low: 'text-emerald-400',
  medium: 'text-amber-400',
  high: 'text-red-400',
}

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getReports()
      .then(setReports)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load reports'),
      )
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-slate-800 px-6 py-4">
        <h2 className="text-lg font-semibold">Reports</h2>
        <p className="mt-1 text-sm text-slate-400">
          Security scans, patch audits, indexing, and access logs
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading && <p className="text-slate-500">Loading…</p>}
        {error && <p className="text-red-300">{error}</p>}

        <div className="grid gap-4 md:grid-cols-2">
          {reports.map((report) => (
            <article
              key={report.id}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
            >
              <div className="flex items-start justify-between gap-2">
                <span
                  className={`rounded-full border px-2 py-0.5 text-xs font-medium uppercase ${typeColors[report.type]}`}
                >
                  {report.type}
                </span>
                {report.severity && (
                  <span
                    className={`text-xs font-medium uppercase ${severityColors[report.severity]}`}
                  >
                    {report.severity}
                  </span>
                )}
              </div>
              <h3 className="mt-3 font-medium text-slate-100">{report.title}</h3>
              <p className="mt-2 text-sm text-slate-400">{report.summary}</p>
              <p className="mt-3 text-xs text-slate-500">
                {report.projectName} ·{' '}
                {new Date(report.createdAt).toLocaleString()}
              </p>
            </article>
          ))}
        </div>
      </div>
    </div>
  )
}
