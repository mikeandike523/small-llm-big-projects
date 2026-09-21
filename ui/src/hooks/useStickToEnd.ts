import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

const NEAR_END_THRESHOLD_PX = 32;

// Replaces @tanstack/react-virtual's built-in anchorTo/followOnAppend for a
// virtualized list that should behave like a chat/log window: stick to the
// bottom as content arrives, stop the instant the user scrolls up, and
// resume once they scroll back down to the bottom themselves.
//
// Returns a boolean reflecting the current lock state — true when the view
// is auto-scrolling to follow new content, false when the user has scrolled
// away. Callers typically render this as a bottom-edge shine indicator.
export function useStickToEnd<TScrollElement extends Element>(
  virtualizer: Virtualizer<TScrollElement, Element>,
): boolean {
  const prevCountRef = useRef(0);
  const stuckRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const [isAutoScrolling, setIsAutoScrolling] = useState(true);

  // Stable ref so long-lived closures always call the latest virtualizer.
  const vRef = useRef(virtualizer);
  vRef.current = virtualizer;

  useEffect(() => {
    const el = virtualizer.scrollElement;
    if (!el) return;

    const onScroll = () => {
      const distanceFromEnd =
        el.scrollHeight - (el.scrollTop + el.clientHeight);

      // Scroll-up always unlocks and cancels all future programmatic
      // scrolling (stuckRef=false blocks both phases from snapping).
      if (el.scrollTop < lastScrollTopRef.current) {
        stuckRef.current = false;
        setIsAutoScrolling(false);
      } else if (distanceFromEnd <= NEAR_END_THRESHOLD_PX) {
        stuckRef.current = true;
        setIsAutoScrolling(true);
      }

      lastScrollTopRef.current = el.scrollTop;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [virtualizer.scrollElement]);

  // Phase 1 — pre-paint (useLayoutEffect, no deps):
  // Only scrolls when the item count increases. Gating on count (rather
  // than scrolling on every render) drastically reduces programmatic
  // scroll events that can race with user input. Row-growing-in-place
  // is still caught by Phase 2 via getTotalSize().
  useLayoutEffect(() => {
    if (!stuckRef.current) return;
    const count = vRef.current.options.count;
    if (count <= prevCountRef.current) return;
    prevCountRef.current = count;
    vRef.current.scrollToEnd({ behavior: "instant" });
  });

  // Phase 2 — post-paint (useEffect, watches total size):
  // Safety net for the "starts small, floods large" edge case. When a
  // burst of new items arrives, phase-1 scrollToEnd may use estimated
  // sizes for items outside the visible range. After paint those items
  // are rendered, measured by the virtualizer, and getTotalSize() may
  // grow. Re-snap here to correct onto the true bottom.
  //
  // Also serves as the guaranteed first-mount scroll — even when content
  // hasn't appeared yet (getTotalSize() starts at 0), it fires once on
  // mount so we're ready when the first real size lands.
  useEffect(() => {
    if (!stuckRef.current) return;
    vRef.current.scrollToEnd({ behavior: "instant" });
  }, [virtualizer.getTotalSize()]);

  return isAutoScrolling;
}