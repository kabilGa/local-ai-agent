import { cn } from '@/lib/utils'

export type SecuritySeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM'

export type SecurityFinding = {
  id: string
  title: string
  file: string
  line: number
  severity: SecuritySeverity
  description: string
}

export const MOCK_SECURITY_FINDINGS: SecurityFinding[] = [
  {
    id: 'sf-1',
    title: 'SQL injection vector in query builder',
    file: 'services/api-gateway/db/queries.ts',
    line: 84,
    severity: 'CRITICAL',
    description: 'User input concatenated into raw SQL without parameterization.',
  },
  {
    id: 'sf-2',
    title: 'Hardcoded API key in config',
    file: 'src/config/env.ts',
    line: 12,
    severity: 'HIGH',
    description: 'Secret key committed to repository; rotate immediately.',
  },
  {
    id: 'sf-3',
    title: 'Missing CSRF token on state-changing route',
    file: 'src/api/patches.ts',
    line: 31,
    severity: 'MEDIUM',
    description: 'POST endpoint lacks CSRF validation middleware.',
  },
]

const severityStyles: Record<SecuritySeverity, string> = {
  CRITICAL: 'bg-red-950/60 text-red-300 border-red-800',
  HIGH: 'bg-amber-950/50 text-amber-300 border-amber-800',
  MEDIUM: 'bg-yellow-950/40 text-yellow-200/80 border-yellow-800/50',
}

export type SecurityFindingsPanelProps = {
  findings?: SecurityFinding[]
  className?: string
}

export default function SecurityFindingsPanel({
  findings = MOCK_SECURITY_FINDINGS,
  className,
}: SecurityFindingsPanelProps) {
  return (
    <aside
      className={cn(
        'flex w-72 shrink-0 flex-col border-l border-[#1e1e2e] bg-[#0a0a0f]',
        className,
      )}
    >
      <div className="border-b border-[#1e1e2e] px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-200">Security Findings</h3>
        <p className="mt-0.5 text-xs text-slate-500">{findings.length} issues detected</p>
      </div>

      <ul className="flex-1 space-y-2 overflow-y-auto p-3">
        {findings.map((finding) => (
          <li
            key={finding.id}
            className="rounded-lg border border-[#1e1e2e] bg-[#111118] p-3"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium text-slate-200">{finding.title}</p>
              <span
                className={cn(
                  'shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-semibold',
                  severityStyles[finding.severity],
                )}
              >
                {finding.severity}
              </span>
            </div>
            <p className="mt-2 font-mono text-xs text-[#7c3aed]">
              {finding.file}:{finding.line}
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              {finding.description}
            </p>
          </li>
        ))}
      </ul>
    </aside>
  )
}
