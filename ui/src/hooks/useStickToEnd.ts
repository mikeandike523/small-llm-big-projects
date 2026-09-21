import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

const NEAR_END_THRESHOLD_PX = 32;

// Controls how Phase 2 reacts to total-size changes:
//   "increase" — only scroll when getTotalSize() grows (monotonically up).
//                 Ignores decreases and fluctuations from re-measurement.
//   "change"   — scroll on every getTotalSize() change, matching the
//                 original behaviour. More aggressive but covers all gaps.
const PHASE_2_MODE: "increase" | "change" = "increase";

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
  const prevTotalSizeRef = useRef(0);
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

  // Only scroll when the item count increases — this eliminates spurious
  // scrolls from in-place growth or virtualizer re-measurements. A single
  // RAF after the scroll corrects for any estimate→actual gap once the
  // virtualizer has measured newly-visible items.
  useLayoutEffect(() => {
    if (!stuckRef.current) return;
    const count = vRef.current.options.count;
    if (count <= prevCountRef.current) return;
    prevCountRef.current = count;
    vRef.current.scrollToEnd({ behavior: "instant" });
    requestAnimationFrame(() => {
      if (!stuckRef.current) return;
      vRef.current.scrollToEnd({ behavior: "instant" });
    });
  });

  // Phase 2 — totalSize-gated: catches what Phase 1 misses.
  //   a) Estimate→actual gap: Phase 1 scrolls with estimates; after paint
  //      the virtualizer measures true sizes and getTotalSize() changes.
  //   b) In-place growth: a rendered item gets taller (streaming text) but
  //      count doesn't change, so Phase 1 skips.
  // Behaviour controlled by PHASE_2_MODE above.
  useEffect(() => {
    if (!stuckRef.current) return;
    const totalSize = vRef.current.getTotalSize();
    if (PHASE_2_MODE === "increase" && totalSize <= prevTotalSizeRef.current) return;
    prevTotalSizeRef.current = totalSize;
    vRef.current.scrollToEnd({ behavior: "instant" });
  }, [virtualizer.getTotalSize()]);

  return isAutoScrolling;
}
