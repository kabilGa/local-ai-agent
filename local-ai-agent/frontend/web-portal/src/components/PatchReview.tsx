import { useState } from 'react'
import { applyPatch, rejectPatch } from '../api/patches'
import GitDiffViewer from './diff/GitDiffViewer'
import type { PatchProposal } from '../types'

type PatchReviewProps = {
  patch: PatchProposal
  onUpdate: (patch: PatchProposal) => void
}

export default function PatchReview({ patch, onUpdate }: PatchReviewProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleApply() {
    setBusy(true)
    setError(null)
    try {
      onUpdate(await applyPatch(patch.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply patch')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject() {
    setBusy(true)
    setError(null)
    try {
      onUpdate(await rejectPatch(patch.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject patch')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 space-y-3">
      <div>
        <h3 className="font-semibold text-slate-100">{patch.title}</h3>
        <p className="mt-1 text-sm text-slate-400">{patch.explanation}</p>
      </div>

      <GitDiffViewer
        file={patch.file}
        lines={patch.diff}
        status={patch.status}
        onAccept={handleApply}
        onReject={handleReject}
        busy={busy}
      />

      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium text-slate-500">Risks</p>
          <ul className="mt-1 list-inside list-disc text-slate-300">
            {patch.risks.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-xs font-medium text-slate-500">Tests run</p>
          <ul className="mt-1 list-inside list-disc text-slate-300">
            {patch.testsRun.map((t) => (
              <li key={t}>
                <code className="font-mono text-xs">{t}</code>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <p className="text-xs text-slate-500">
        Confidence: {(patch.confidence * 100).toFixed(0)}%
      </p>

      {error && <p className="text-sm text-red-300">{error}</p>}
    </div>
  )
}
