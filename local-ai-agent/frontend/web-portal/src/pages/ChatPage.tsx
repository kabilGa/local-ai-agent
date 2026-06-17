import { useMemo, useState } from 'react'
import { streamChatMessage } from '../api/chat'
import ChatMessageBubble from '../components/chat/ChatMessageBubble'
import TokenUsageMonitor from '../components/chat/TokenUsageMonitor'
import PatchReview from '../components/PatchReview'
import ProjectSelector from '../components/ProjectSelector'
import SourceCitationList from '../components/SourceCitationList'
import SecurityFindingsPanel from '../components/security/SecurityFindingsPanel'
import { AI_Prompt } from '@/components/ui/animated-ai-input'
import { useAutoScroll } from '@/hooks/useAutoScroll'
import { estimateTokens } from '@/lib/parseMarkdown'
import { useProject } from '../context/ProjectContext'
import type { ChatMessage, PatchProposal } from '../types'

export default function ChatPage() {
  const { selectedProject, explainMode } = useProject()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [attachedFiles, setAttachedFiles] = useState<string[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string | undefined>()
  const [showSecurity, setShowSecurity] = useState(false)

  const streamKey = useMemo(
    () => messages.map((m) => `${m.id}:${m.text.length}:${m.streaming}`).join('|'),
    [messages],
  )
  const { containerRef, bottomRef } = useAutoScroll(streamKey)

  const tokensUsed = useMemo(
    () => messages.reduce((sum, m) => sum + estimateTokens(m.text), 0),
    [messages],
  )

  function updatePatchInMessages(patch: PatchProposal) {
    setMessages((prev) =>
      prev.map((m) => (m.patch?.id === patch.id ? { ...m, patch } : m)),
    )
  }

  function handleAttachFiles(files: string[]) {
    setAttachedFiles((prev) => [...new Set([...prev, ...files])])
  }

  function handleRemoveFile(file: string) {
    setAttachedFiles((prev) => prev.filter((f) => f !== file))
  }

  async function sendMessage(trimmed: string) {
    if (!trimmed || isLoading || !selectedProject) return

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      text: trimmed,
    }

    const assistantId = crypto.randomUUID()
    setMessages((prev) => [
      ...prev,
      userMessage,
      { id: assistantId, role: 'assistant', text: '', streaming: true },
    ])
    setError(null)
    setIsLoading(true)

    const wantsSecurity =
      trimmed.toLowerCase().includes('security') ||
      trimmed.toLowerCase().includes('vulner')
    if (wantsSecurity) setShowSecurity(true)

    try {
      const stream = streamChatMessage({
        message: trimmed,
        project: selectedProject.name,
        explainMode,
        conversationId,
      })

      let fullText = ''
      let result = await stream.next()

      while (!result.done) {
        fullText += result.value
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, text: fullText, streaming: true } : m,
          ),
        )
        result = await stream.next()
      }

      const response = result.value
      setConversationId(response.conversationId)

      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                text: response.response,
                streaming: false,
                sources: response.sources,
                patch: response.patch,
              }
            : m,
        ),
      )
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== assistantId))
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex h-full flex-col bg-[#0a0a0f]">
      <header className="border-b border-[#1e1e2e] px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="text-lg font-semibold text-slate-100">Chat</h2>
          <TokenUsageMonitor used={tokensUsed} />
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <ProjectSelector />
          <button
            type="button"
            onClick={() => setShowSecurity((v) => !v)}
            className="rounded-lg border border-[#1e1e2e] px-3 py-1.5 text-xs text-slate-400 hover:bg-[#111118] hover:text-slate-200"
          >
            {showSecurity ? 'Hide' : 'Show'} security panel
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <div
          ref={containerRef}
          className="flex flex-1 flex-col gap-4 overflow-y-auto px-6 py-6"
        >
          {messages.length === 0 && (
            <p className="text-center text-slate-500">
              Ask about your code, try &quot;fix this bug&quot; for a diff, or
              &quot;security scan&quot; for findings.
            </p>
          )}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={`max-w-[85%] ${msg.role === 'user' ? 'ml-auto' : 'mr-auto'}`}
            >
              <ChatMessageBubble
                role={msg.role}
                text={msg.text}
                streaming={msg.streaming}
              />

              {msg.sources && <SourceCitationList sources={msg.sources} />}

              {msg.patch && (
                <PatchReview patch={msg.patch} onUpdate={updatePatchInMessages} />
              )}
            </div>
          ))}

          {error && (
            <p className="rounded-lg border border-red-800 bg-red-950/50 px-4 py-2 text-sm text-red-300">
              {error}
            </p>
          )}
          <div ref={bottomRef} />
        </div>

        {showSecurity && <SecurityFindingsPanel />}
      </div>

      <div className="border-t border-[#1e1e2e] px-6 py-3">
        <AI_Prompt
          onSend={sendMessage}
          disabled={isLoading || !selectedProject}
          placeholder="Ask about your repo, a file, or a bug…"
          attachedFiles={attachedFiles}
          onAttachFiles={handleAttachFiles}
          onRemoveFile={handleRemoveFile}
        />
      </div>
    </div>
  )
}
