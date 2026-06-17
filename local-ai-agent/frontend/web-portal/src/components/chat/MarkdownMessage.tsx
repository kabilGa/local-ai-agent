import { parseMarkdown } from '@/lib/parseMarkdown'
import CodeBlock from './CodeBlock'

export type MarkdownMessageProps = {
  text: string
  streaming?: boolean
}

export default function MarkdownMessage({ text, streaming }: MarkdownMessageProps) {
  const segments = parseMarkdown(text)

  return (
    <div className="space-y-1 text-sm leading-relaxed">
      {segments.map((segment, i) =>
        segment.type === 'code' ? (
          <CodeBlock
            key={i}
            language={segment.language}
            code={segment.content}
          />
        ) : (
          <p key={i} className="whitespace-pre-wrap">
            {segment.content}
          </p>
        ),
      )}
      {streaming && (
        <span className="ml-0.5 inline-block h-4 w-1 animate-pulse bg-[#7c3aed]" />
      )}
    </div>
  )
}
