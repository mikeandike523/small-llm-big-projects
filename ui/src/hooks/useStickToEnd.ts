import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

const NEAR_END_THRESHOLD_PX = 32;

// How long the "just auto-scrolled" indicator stays lit after the most
// recent auto-scroll before it's allowed to fade out — long enough to read
// as one continuous glow during a burst of streaming updates, short enough
// to read as "just happened" once they stop.
const INDICATOR_LINGER_MS = 400;

// Replaces @tanstack/react-virtual's built-in anchorTo/followOnAppend for a
// virtualized list that should behave like a chat/log window: stick to the
// bottom as content arrives, stop the instant the user scrolls up, and
// resume once they scroll back down to the bottom themselves.
//
// followOnAppend only re-sticks when the row COUNT grows. It does not
// re-stick when the last (still-live) row grows in place — e.g. a tool
// call's streamingResult filling in character by character, or a patch
// rewrite banner appearing mid-row — which is why the list stopped tracking
// bottom during streaming even with accurate size estimates. This hook
// re-checks and re-snaps after every render instead, so it responds to
// whatever state change caused the host component to re-render, not just
// to new rows being appended.
//
// Returns whether it's currently (or very recently) auto-scrolled, for a
// caller to render as a brief visual indicator — e.g. a fading bottom shine.
export function useStickToEnd<TScrollElement extends Element>(
  virtualizer: Virtualizer<TScrollElement, Element>,
): boolean {
  const stuckRef = useRef(true);
  const programmaticScrollRef = useRef(false);
  const lastScrollTopRef = useRef(0);
  const lingerTimeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const [isAutoScrolling, setIsAutoScrolling] = useState(false);

  useEffect(() => {
    const el = virtualizer.scrollElement;
    if (!el) return;

    const onScroll = () => {
      if (programmaticScrollRef.current) return;

      const distanceFromEnd =
        el.scrollHeight - (el.scrollTop + el.clientHeight);

      if (distanceFromEnd <= NEAR_END_THRESHOLD_PX) {
        stuckRef.current = true;
      } else if (el.scrollTop < lastScrollTopRef.current) {
        stuckRef.current = false; // user scrolled up
        clearTimeout(lingerTimeoutRef.current);
        setIsAutoScrolling(false);
      }
      lastScrollTopRef.current = el.scrollTop;
    };

    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [virtualizer.scrollElement]);

  // No dependency array: this must re-check on every render, since the last
  // row can grow taller from streaming content without the row count (or
  // any single dependency we could name here) changing.
  useLayoutEffect(() => {
    if (!stuckRef.current) return;

    programmaticScrollRef.current = true;
    virtualizer.scrollToEnd({ behavior: "instant" });
    // Native scroll events from this call fire asynchronously; release the
    // guard on the next frame so they aren't misread as a user scroll-up.
    const id = requestAnimationFrame(() => {
      programmaticScrollRef.current = false;
    });

    setIsAutoScrolling(true);
    clearTimeout(lingerTimeoutRef.current);
    lingerTimeoutRef.current = setTimeout(() => {
      setIsAutoScrolling(false);
    }, INDICATOR_LINGER_MS);

    return () => cancelAnimationFrame(id);
  });

  useEffect(() => {
    return () => clearTimeout(lingerTimeoutRef.current);
  }, []);

  return isAutoScrolling;
}
