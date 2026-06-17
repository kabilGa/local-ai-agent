import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getConversations } from '../api/history'
import type { ConversationSummary } from '../types'

export default function HistoryPage() {
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getConversations()
      .then(setConversations)
      .catch((err) =>
        setError(err instanceof Error ? err.message : 'Failed to load history'),
      )
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-slate-800 px-6 py-4">
        <h2 className="text-lg font-semibold">Conversation history</h2>
        <p className="mt-1 text-sm text-slate-400">
          Past sessions with patch status and message counts
        </p>
      </header>

      <div className="flex-1 overflow-y-auto px-6 py-6">
        {loading && <p className="text-slate-500">Loading…</p>}
        {error && <p className="text-red-300">{error}</p>}

        {!loading && conversations.length === 0 && (
          <p className="text-slate-500">No conversations yet.</p>
        )}

        <ul className="space-y-3">
          {conversations.map((conv) => (
            <li
              key={conv.id}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h3 className="font-medium text-slate-100">{conv.title}</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    {conv.projectName} · {conv.messageCount} messages
                  </p>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <p>{new Date(conv.lastMessageAt).toLocaleString()}</p>
                  {conv.patchStatus && (
                    <p
                      className={`mt-1 font-medium uppercase ${
                        conv.patchStatus === 'applied'
                          ? 'text-emerald-400'
                          : conv.patchStatus === 'rejected'
                            ? 'text-red-400'
                            : 'text-amber-400'
                      }`}
                    >
                      Patch {conv.patchStatus}
                    </p>
                  )}
                </div>
              </div>
              <Link
                to="/chat"
                className="mt-3 inline-block text-sm text-violet-400 hover:text-violet-300"
              >
                Continue in chat →
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
