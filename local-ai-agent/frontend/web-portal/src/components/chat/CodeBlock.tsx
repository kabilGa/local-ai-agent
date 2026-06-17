import type { ReactNode } from 'react'
import { useCopyToClipboard } from '@/hooks/useCopyToClipboard'
import { cn } from '@/lib/utils'

export type CodeBlockProps = {
  language: string
  code: string
  className?: string
}

const TS_KEYWORD_RE =
  /^const$|^let$|^var$|^function$|^return$|^import$|^export$|^from$|^async$|^await$|^if$|^else$|^type$|^interface$/

function highlightLine(line: string, language: string): ReactNode {
  if (['typescript', 'javascript', 'ts', 'tsx'].includes(language)) {
    return line
      .split(
        /(\b(?:const|let|var|function|return|import|export|from|async|await|if|else|type|interface)\b)/,
      )
      .map((part, i) =>
        TS_KEYWORD_RE.test(part) ? (
          <span key={i} className="text-[#7c3aed]">
            {part}
          </span>
        ) : (
          <span key={i}>{part}</span>
        ),
      )
  }
  return line
}

export default function CodeBlock({ language, code, className }: CodeBlockProps) {
  const { copied, copy } = useCopyToClipboard()

  return (
    <div
      className={cn(
        'my-3 overflow-hidden rounded-lg border border-[#1e1e2e] bg-[#111118]',
        className,
      )}
    >
      <div className="flex items-center justify-between border-b border-[#1e1e2e] bg-[#0a0a0f] px-3 py-2">
        <span className="font-mono text-xs text-slate-400">{language || 'text'}</span>
        <button
          type="button"
          onClick={() => copy(code)}
          className="rounded px-2 py-0.5 font-mono text-xs text-slate-400 transition-colors hover:bg-[#1e1e2e] hover:text-slate-200"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-xs leading-5 text-slate-300">
        <code>
          {code.split('\n').map((line, i) => (
            <div key={i}>{highlightLine(line, language)}</div>
          ))}
        </code>
      </pre>
    </div>
  )
}
