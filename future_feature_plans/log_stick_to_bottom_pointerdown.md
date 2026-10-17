# Stick-to-Bottom: Unstick Only on Recent User Input

## Status

Deferred. Only pursue this if log eviction still causes accidental unsticking
**after** the Backend Logs virtualizer is switched to `anchorTo: "end"`.

## Background

`ui/src/hooks/useStickToEnd.ts` decides whether to keep following the end of a
virtualized list. It unsticks from two signals:

1. `wheel` with `deltaY < 0` -- unambiguous user intent.
2. `scroll` events, inferred from position. Needed because scrollbar drags,
   track clicks, keyboard (PageUp/arrows/Home) and touch drags do not fire
   `wheel`, only `scroll`. But `scroll` also fires for every programmatic
   `scrollTop` change (ours and TanStack's), and the event does not say which.

The inference branch

```ts
if (scrolledUp && distanceFromEnd > AT_END_TOLERANCE_PX) {
  stopFollowing(); // deliberately ignores programmaticScrollRef
}
```

ignores the programmatic guard so a scrollbar drag during streaming can still
win. That means any programmatic upward scroll that a `scroll` handler observes
while it is >1px from the end is misread as the user.

With `anchorTo: "end"`, TanStack writes `scrollTop` on eviction (keeping the
on-screen row fixed: `virtual-core` `setOptions` computes the anchor,
`_willUpdate` applies it via `scrollToFn` -> `element.scrollTo`). Today this is
believed safe: the anchor write and `useStickToEnd`'s `useLayoutEffect(snapToEnd)`
happen in the same commit, and `scroll` events are queued to the next frame, so
the handler only sees the final at-end position. If manual testing (busy
session, buffer rotating, stuck and scrolled-up) shows unexpected unsticks,
this plan is the fix.

## Proposal

Make unsticking require a *recent qualified user input* on the scroll element,
instead of inferring intent from scroll position alone.

- Track the timestamp of the last `wheel`, `keydown`, `touchstart`, and
  `pointerdown` on the scroll element. Clicking or dragging the scrollbar
  generally dispatches `pointerdown` on the scroll element in Chromium (which
  Electron uses) -- verify in Firefox/Safari if the browser UI matters there.
- In `onScroll`, only call `stopFollowing()` when an upward move leaves the end
  AND a qualified input happened within a short window (e.g. 250ms), or a
  pointer is currently held down (between `pointerdown` and
  `pointerup`/`pointercancel`, to cover long scrollbar drags).
- Programmatic scrolls of any origin (snapToEnd, TanStack anchor corrections,
  browser clamping after a row shrinks) then can never unstick.
- Re-stick logic (within `NEAR_END_THRESHOLD_PX` of the end) stays as is.

Sketch:

```ts
const lastUserInputRef = useRef(0);
const pointerHeldRef = useRef(false);

const markInput = () => { lastUserInputRef.current = performance.now(); };
const onPointerDown = () => { pointerHeldRef.current = true; markInput(); };
const onPointerUp = () => { pointerHeldRef.current = false; markInput(); };

const userIsDriving = () =>
  pointerHeldRef.current ||
  performance.now() - lastUserInputRef.current < USER_INPUT_WINDOW_MS;

// in onScroll:
if (scrolledUp && distanceFromEnd > AT_END_TOLERANCE_PX && userIsDriving()) {
  stopFollowing();
}
```

`pointerup` should be listened for on `window` (the pointer can be released
outside the scroller).

## Scope warning

`useStickToEnd` is shared: it is also used by `TurnDetails.tsx` (Tool Calls
column). Any change must be tested in both places, so keep it a separate
change from the log filter work.
