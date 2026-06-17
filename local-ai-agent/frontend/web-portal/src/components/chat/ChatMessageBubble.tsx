import { Clipboard } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import MarkdownMessage from './MarkdownMessage'

export type ChatMessageBubbleProps = {
  role: 'user' | 'assistant'
  text: string
  streaming?: boolean
  className?: string
}

export default function ChatMessageBubble({
  role,
  text,
  streaming,
  className,
}: ChatMessageBubbleProps) {
  const [copied, setCopied] = useState(false)
  const isUser = role === 'user'

  async function handleCopy() {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      className={cn(
        'group relative max-w-full',
        isUser ? 'ml-auto' : 'mr-auto',
        className,
      )}
    >
      <button
        type="button"
        onClick={handleCopy}
        aria-label="Copy message"
        className={cn(
          'absolute -top-2 z-10 rounded-md border border-[#1e1e2e] bg-[#111118] px-2 py-1 font-mono text-[10px] text-slate-400 opacity-0 transition-opacity group-hover:opacity-100 hover:text-slate-200',
          isUser ? 'left-0 -translate-x-full' : 'right-0 translate-x-full',
        )}
      >
        {copied ? (
          'Copied!'
        ) : (
          <Clipboard className="h-3.5 w-3.5" />
        )}
      </button>

      <div
        className={cn(
          'rounded-2xl px-4 py-3',
          isUser
            ? 'bg-[#7c3aed] text-white'
            : 'border border-[#1e1e2e] bg-[#111118] text-slate-100',
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{text}</p>
        ) : (
          <MarkdownMessage text={text} streaming={streaming} />
        )}
      </div>
    </div>
  )
}
