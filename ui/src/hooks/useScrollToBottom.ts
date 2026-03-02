import { useRef, useCallback, useMemo, useEffect, useLayoutEffect } from 'react'
import throttle from 'lodash.throttle'
import { SCROLL_BOTTOM_THRESHOLD, SCROLL_THROTTLE_MS } from '../constants'

const SCROLL_PERSIST_DEBOUNCE_MS = 200

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
 * - Optional `persistId`: if set, restores scroll position from sessionStorage on
 *   mount and saves it (debounced) on scroll.
 */
export function useScrollToBottom<T extends HTMLElement = HTMLDivElement>({
  persistId,
}: { persistId?: string } = {}) {
  const containerRef = useRef<T>(null)
  const isAtBottom = useRef(true)
  const lastScrollTopRef = useRef(0)
  const persistDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Restore scroll position from sessionStorage on mount (if persistId set)
  useLayoutEffect(() => {
    if (!persistId) return
    const el = containerRef.current
    if (!el) return
    const stored = sessionStorage.getItem(`scroll:${persistId}`)
    if (stored !== null) {
      const savedTop = parseInt(stored, 10)
      if (!isNaN(savedTop)) {
        el.scrollTop = savedTop
        const dist = el.scrollHeight - savedTop - el.clientHeight
        isAtBottom.current = dist <= SCROLL_BOTTOM_THRESHOLD
        lastScrollTopRef.current = savedTop
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persistId])

  // Cancel debounced write on unmount
  useEffect(() => {
    return () => {
      if (persistDebounceRef.current !== null) {
        clearTimeout(persistDebounceRef.current)
      }
    }
  }, [])

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

    // Persist scroll position (debounced)
    if (persistId) {
      if (persistDebounceRef.current !== null) {
        clearTimeout(persistDebounceRef.current)
      }
      persistDebounceRef.current = setTimeout(() => {
        sessionStorage.setItem(`scroll:${persistId}`, String(currentScrollTop))
        persistDebounceRef.current = null
      }, SCROLL_PERSIST_DEBOUNCE_MS)
    }
  }, [scrollToBottomIfNeeded, persistId])

  return { containerRef, isAtBottom, scrollToBottomIfNeeded, onScroll }
}
