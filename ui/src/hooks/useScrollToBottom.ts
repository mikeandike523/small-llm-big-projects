import { useRef, useCallback, useMemo, useEffect } from 'react'
import throttle from 'lodash.throttle'
import { SCROLL_BOTTOM_THRESHOLD, SCROLL_THROTTLE_MS } from '../constants'

/**
 * Manages scroll-to-bottom behaviour for a scrollable container.
 *
 * - Tracks whether the user is within SCROLL_BOTTOM_THRESHOLD px of the bottom.
 * - Exposes a throttled `scrollToBottomIfNeeded` that only scrolls when the user
 *   is already at the bottom (or forced via `isAtBottom.current = true`).
 * - `onScroll` should be attached to the container's onScroll event.
 */
export function useScrollToBottom<T extends HTMLElement = HTMLDivElement>() {
  const containerRef = useRef<T>(null)
  const isAtBottom = useRef(true)

  const _scroll = useCallback(() => {
    const el = containerRef.current
    if (!el || !isAtBottom.current) return
    el.scrollTop = el.scrollHeight
  }, [])

  const scrollToBottomIfNeeded = useMemo(
    () => throttle(_scroll, SCROLL_THROTTLE_MS, { leading: true, trailing: true }),
    [_scroll],
  )

  // Cancel any pending throttled call on unmount to avoid state updates on dead components.
  useEffect(() => () => { scrollToBottomIfNeeded.cancel() }, [scrollToBottomIfNeeded])

  const onScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    isAtBottom.current = dist <= SCROLL_BOTTOM_THRESHOLD
  }, [])

  return { containerRef, isAtBottom, scrollToBottomIfNeeded, onScroll }
}
