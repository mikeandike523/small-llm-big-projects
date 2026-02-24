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
 * - Direction-aware: upward scrolls immediately disengage autoscroll and cancel
 *   any pending throttled scroll; downward scrolls re-engage only when the user
 *   reaches the bottom threshold.
 */
export function useScrollToBottom<T extends HTMLElement = HTMLDivElement>() {
  const containerRef = useRef<T>(null)
  const isAtBottom = useRef(true)
  const lastScrollTopRef = useRef(0)

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

    const currentScrollTop = el.scrollTop
    const scrollingUp = currentScrollTop < lastScrollTopRef.current
    lastScrollTopRef.current = currentScrollTop

    if (scrollingUp) {
      // User pulled view upward: disengage and kill any pending scroll
      isAtBottom.current = false
      scrollToBottomIfNeeded.cancel()
    } else {
      // User scrolled down: re-engage only if they reached the bottom
      const dist = el.scrollHeight - currentScrollTop - el.clientHeight
      if (dist <= SCROLL_BOTTOM_THRESHOLD) {
        isAtBottom.current = true
      }
    }
  }, [scrollToBottomIfNeeded])

  return { containerRef, isAtBottom, scrollToBottomIfNeeded, onScroll }
}
