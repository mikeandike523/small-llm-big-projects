# Verifying @tanstack/react-virtual estimateSize Accuracy

## Problem

`useVirtualizer`'s `estimateSize(index)` seeds a row's height before it has
ever been rendered. If the estimate is far off, the virtualizer's computed
scroll offsets/`getTotalSize()` are wrong until `measureElement` corrects
them post-mount — which shows up as scroll-position jumps, especially with
`anchorTo: "end"` / a custom stick-to-bottom hook, since "the bottom" moves
every time an estimate is corrected.

When an estimator (a hand-rolled function mirroring a component's CSS to
predict its rendered height — see `ui/src/estimators/*` in this repo) seems
wrong, or a row appears to collapse to zero height, you need to see the
estimate and the real measured value side by side, per row, as it happens.
Not a one-off print — a stream you can watch while driving the UI.

## Where to hook in

Don't log inside `estimateSize` itself — it fires far more often than
`measureElement` (once per render for every unmeasured index) and this
produces noisy logs. Instead wrap the **`measureElement` option** on
`useVirtualizer`. This fires exactly when the real DOM height is measured:
once on mount, and again via ResizeObserver whenever a rendered row resizes
(e.g. streaming content growing in place). This is also the reachable
integration point for a case that's easy to overlook: a `ref={virtualizer.measureElement}`
in JSX only fires on mount/unmount, so it does NOT recapture a row resizing
in place. Wrapping the `measureElement` *option* passed to `useVirtualizer`
covers both.

```ts
import {
  useVirtualizer,
  measureElement as measureVirtualElement, // the library's default (real) measurement fn
} from "@tanstack/react-virtual";

// Hoist the estimator call so both estimateSize and the logging wrapper
// call the exact same logic — no duplicated/drifted estimate math.
const estimateRowSize = (index: number): number =>
  myEstimator(myRows[index], scrollRef.current?.clientWidth ?? FALLBACK_WIDTH);

const virtualizer = useVirtualizer({
  count: myRows.length,
  getScrollElement: () => scrollRef.current,
  estimateSize: estimateRowSize,
  getItemKey: (index) => myRows[index].id,
  measureElement: (el, entry, instance) => {
    const measured = measureVirtualElement(el, entry, instance);
    const index = instance.indexFromElement(el); // reads the data-index attr
    const row = myRows[index];
    const estimated = estimateRowSize(index); // recompute fresh — see note below
    const previous = instance.measurementsCache[index]?.size;
    const log = measured === 0 ? console.warn : console.log;
    log(
      `[estimator][my-list] type=${row?.type ?? "?"} index=${index} ` +
        `key=${row?.id ?? "?"} estimatedPx=${estimated} measuredPx=${measured} ` +
        `previousPx=${previous ?? "?"}${measured === 0 ? " <-- ZERO HEIGHT" : ""}`,
    );
    return measured; // must still return the real value — this is a pass-through wrapper
  },
});
```

`instance.indexFromElement(el)` reads the `data-index` attribute your row
JSX already sets for the virtualizer to work at all — no extra wiring needed.

## Why log three numbers, not two

- **`estimatedPx`** — call the estimator function directly, right now, at
  this index. Don't rely on `previousPx` to stand in for "what the estimator
  says" — that's only true the *first* time a row is measured. On any later
  re-measurement (a row resizing in place during streaming), `previousPx` is
  the last *measured* value, not the estimate, so it can't tell you whether
  the estimator itself is accurate past first mount.
- **`measuredPx`** — the real value, straight from the library's own
  `measureElement` default implementation (imported and called directly, so
  the wrapper stays a transparent pass-through and doesn't change behavior).
- **`previousPx`** — `instance.measurementsCache[index]?.size`, whatever the
  virtualizer had cached going in. Useful for watching a row's height evolve
  across repeated re-measurements (e.g. watching a streaming tool result grow
  line by line), separate from the one-shot estimate-vs-measured comparison.

## Flagging zero-height rows

A real collapsed-content bug (missing CSS, empty conditional render, a
component returning `null` unexpectedly) shows up as `measuredPx=0`. Route
that case to `console.warn` instead of `console.log` and append a distinct
marker so it's easy to spot/filter in a noisy stream:

```ts
const log = measured === 0 ? console.warn : console.log;
log(`... measuredPx=${measured} ...${measured === 0 ? " <-- ZERO HEIGHT" : ""}`);
```

## Cleanup

This is debug instrumentation, not something to ship. Once you've verified
the estimator (or found and fixed the real bug), remove:

1. The `measureElement:` option block from `useVirtualizer(...)` (deleting it
   restores the library's default measurement behavior automatically — the
   JSX `ref={virtualizer.measureElement}` doesn't need to change).
2. The `measureElement as measureVirtualElement` import if nothing else in
   the file uses it.

Keep the hoisted `estimateRowSize`-style function if `estimateSize` still
uses it (it usually does) — only the logging wrapper around `measureElement`
is temporary.

## Worked example

Added and later removed in this repo for the tool-calls bubble list
(`ui/src/components/TurnContainer.tsx`) and the debug panel logs tab
(`ui/src/subcomponents/DebugPanel/BackendLogsTab.tsx`), while verifying the
estimators in `ui/src/estimators/tool-call-bubble/` and
`ui/src/estimators/backend-log-entry/`. Grep git history for
`[estimator][tool-call-bubble]` / `[estimator][backend-log-entry]` if you
want the exact diff to copy from again.
