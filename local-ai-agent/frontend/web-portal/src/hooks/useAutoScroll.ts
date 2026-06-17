import { useCallback, useEffect, useRef } from 'react'

const NEAR_BOTTOM_PX = 120

export function useAutoScroll(trigger: unknown) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    bottomRef.current?.scrollIntoView({ behavior, block: 'end' })
  }, [])

  useEffect(() => {
    const container = containerRef.current
    if (!container) {
      scrollToBottom('smooth')
      return
    }

    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight
    const shouldFollow = distanceFromBottom <= NEAR_BOTTOM_PX

    if (shouldFollow) {
      scrollToBottom('smooth')
    }
  }, [trigger, scrollToBottom])

  return { containerRef, bottomRef, scrollToBottom }
}
