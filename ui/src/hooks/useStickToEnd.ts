import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

const NEAR_END_THRESHOLD_PX = 32;
const AT_END_TOLERANCE_PX = 1;

// Keeps a virtualized chat/log viewport pinned to its end until the user
// scrolls up. New rows and rows that grow in place are handled identically,
// so callers only need to pass their virtualizer.
export function useStickToEnd<TScrollElement extends Element>(
  virtualizer: Virtualizer<TScrollElement, Element>,
): boolean {
  const stuckRef = useRef(true);
  const programmaticScrollRef = useRef(false);
  const releaseRafRef = useRef<number>();
  const lastScrollTopRef = useRef(0);
  const [isAutoScrolling, setIsAutoScrolling] = useState(true);

  // Long-lived callbacks must use the current virtualizer instance.
  const virtualizerRef = useRef(virtualizer);
  virtualizerRef.current = virtualizer;

  const snapToEnd = useCallback(() => {
    if (!stuckRef.current) return;

    programmaticScrollRef.current = true;
    virtualizerRef.current.scrollToEnd({ behavior: "instant" });

    // scroll events caused by scrollToEnd are delivered asynchronously. Keep
    // the guard through the following frame so a measurement correction that
    // moves scrollTop upward is not mistaken for user intent.
    cancelAnimationFrame(releaseRafRef.current ?? 0);
    releaseRafRef.current = requestAnimationFrame(() => {
      releaseRafRef.current = requestAnimationFrame(() => {
        programmaticScrollRef.current = false;
      });
    });
  }, []);

  useEffect(() => {
    const el = virtualizer.scrollElement;
    if (!el) return;

    lastScrollTopRef.current = el.scrollTop;

    const stopFollowing = () => {
      stuckRef.current = false;
      setIsAutoScrolling(false);
    };

    const onWheel = (event: Event) => {
      if ((event as WheelEvent).deltaY < 0) stopFollowing();
    };

    const onScroll = () => {
      const distanceFromEnd =
        el.scrollHeight - (el.scrollTop + el.clientHeight);
      const scrolledUp = el.scrollTop < lastScrollTopRef.current;

      // A scrollbar or touch drag can happen while streaming renders keep the
      // programmatic guard active. If an upward move actually leaves the end,
      // it is user intent and must win. Measurement corrections may also move
      // scrollTop upward, but they remain at the end and are ignored here.
      if (scrolledUp && distanceFromEnd > AT_END_TOLERANCE_PX) {
        stopFollowing();
      } else if (!programmaticScrollRef.current) {
        if (scrolledUp) {
          stopFollowing();
        } else if (distanceFromEnd <= NEAR_END_THRESHOLD_PX) {
          stuckRef.current = true;
          setIsAutoScrolling(true);
        }
      }

      lastScrollTopRef.current = el.scrollTop;
    };

    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("scroll", onScroll);
    };
  }, [virtualizer.scrollElement]);

  // Run after every host render. This covers both appended rows and streamed
  // content that makes the final row taller without changing the item count.
  useLayoutEffect(snapToEnd);

  // TanStack can discover actual row sizes after the layout pass. Re-snap
  // when that changes its total so estimates cannot leave a gap at the end.
  const totalSize = virtualizer.getTotalSize();
  useEffect(snapToEnd, [snapToEnd, totalSize]);

  useEffect(
    () => () => {
      cancelAnimationFrame(releaseRafRef.current ?? 0);
    },
    [],
  );

  return isAutoScrolling;
}
