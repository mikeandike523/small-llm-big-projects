/**
 * One turn per page: the turn count, the current page and the turn cache.
 *
 * The client never holds the full list of turn ids. It knows the number of
 * turns, the latest turn's id, and a page -> turn id map filled in as pages
 * load (`load_turn {page}` answers with the page's turn id).
 *
 * `thread` (owned by useSocketWiring) is the cache of loaded turns, in no
 * particular order; live socket handlers update turns in it by id. This hook
 * decides what the cache holds:
 *
 *   - the latest turn, always (live events keep updating it);
 *   - the current page's turn and its previous/next neighbors (prefetched);
 *   - the turns of the last RECENT_PAGES_KEPT visited pages.
 *
 * Everything else is evicted when the page changes. The current page is
 * mirrored to `?turn=N` so a reload keeps the reader's place.
 */
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { Socket } from "socket.io-client";
import type { Turn } from "../types";
import { backendTurnToFrontendTurn, requestTurn } from "./turnLoad";

const RECENT_PAGES_KEPT = 5;

type PageTurnIds = Record<number, string>;

function readTurnParam(): number | null {
  const raw = new URLSearchParams(window.location.search).get("turn");
  return raw && /^\d+$/.test(raw) ? Number(raw) : null;
}

function writeTurnParam(page: number) {
  const url = new URL(window.location.href);
  if (url.searchParams.get("turn") === String(page)) return;
  url.searchParams.set("turn", String(page));
  window.history.replaceState(window.history.state, "", url);
}

export default function useTurnPages(
  socket: Socket,
  thread: Turn[],
  setThread: Dispatch<SetStateAction<Turn[]>>,
) {
  const [turnCount, setTurnCountState] = useState(0);
  // Known turn id per 1-based page (the latest page is always known).
  const [pageTurnIds, setPageTurnIdsState] = useState<PageTurnIds>({});
  // 1-based page number; 0 while there is no turn to show.
  const [page, setPageState] = useState(0);
  const [ready, setReady] = useState(false);
  // A turn started (or the latest was followed up) while another page showed.
  const [unseenLatest, setUnseenLatest] = useState(false);
  // Load errors by page.
  const [turnErrors, setTurnErrors] = useState<Record<number, string>>({});

  // Refs mirror the state so socket handlers read current values.
  const turnCountRef = useRef(0);
  const pageTurnIdsRef = useRef<PageTurnIds>({});
  const pageRef = useRef(0);
  const readyRef = useRef(false);
  const recentPagesRef = useRef<number[]>([]);
  const inFlightRef = useRef(new Set<number>());
  // Bumped on reset so responses to an earlier connection are ignored.
  const generationRef = useRef(0);
  // Set when the user sends a message: show the turn it starts.
  const followNextTurnRef = useRef(false);

  const setTurnCount = useCallback((n: number) => {
    turnCountRef.current = n;
    setTurnCountState(n);
  }, []);

  const setPageTurnId = useCallback((n: number, turnId: string) => {
    if (pageTurnIdsRef.current[n] === turnId) return;
    pageTurnIdsRef.current = { ...pageTurnIdsRef.current, [n]: turnId };
    setPageTurnIdsState(pageTurnIdsRef.current);
  }, []);

  const goToPage = useCallback((n: number) => {
    if (!Number.isInteger(n) || n < 1 || n > turnCountRef.current) return;
    pageRef.current = n;
    setPageState(n);
    recentPagesRef.current = [
      ...recentPagesRef.current.filter((x) => x !== n),
      n,
    ].slice(-RECENT_PAGES_KEPT);
    if (n === turnCountRef.current) setUnseenLatest(false);
    writeTurnParam(n);
  }, []);

  /** Forget the turn list; called on every (re)connect. The page is kept. */
  const reset = useCallback(() => {
    generationRef.current += 1;
    readyRef.current = false;
    setReady(false);
    inFlightRef.current = new Set();
    followNextTurnRef.current = false;
    setTurnErrors({});
    setTurnCount(0);
    pageTurnIdsRef.current = {};
    setPageTurnIdsState({});
  }, [setTurnCount]);

  /** The latest-turn load answered with the turn count and the latest id. */
  const setInitialTurns = useCallback(
    (count: number, latestTurnId: string | null) => {
      setTurnCount(count);
      if (count > 0 && latestTurnId) setPageTurnId(count, latestTurnId);
    },
    [setTurnCount, setPageTurnId],
  );

  /**
   * The latest-turn load finished: show the page we were on (reconnect), else
   * the URL's `?turn=N` (first load), else the latest turn.
   */
  const markReady = useCallback(() => {
    readyRef.current = true;
    setReady(true);
    const n = turnCountRef.current;
    if (n === 0) {
      pageRef.current = 0;
      setPageState(0);
      return;
    }
    const wanted = pageRef.current || readTurnParam() || n;
    goToPage(wanted <= n ? wanted : n);
  }, [goToPage]);

  /** A turn_start arrived (live or replayed). */
  const noteTurnStarted = useCallback(
    (turnId: string) => {
      const known = Object.entries(pageTurnIdsRef.current).find(
        ([, id]) => id === turnId,
      );
      let index: number;
      if (known) {
        // A follow-up reopened the latest turn.
        index = Number(known[0]);
      } else {
        index = turnCountRef.current + 1;
        setTurnCount(index);
        setPageTurnId(index, turnId);
      }
      if (!readyRef.current) return;
      if (followNextTurnRef.current || pageRef.current === 0) {
        followNextTurnRef.current = false;
        goToPage(index);
      } else if (pageRef.current !== index) {
        // A new turn, or a follow-up to the latest one, on another page.
        setUnseenLatest(true);
      }
    },
    [goToPage, setTurnCount, setPageTurnId],
  );

  /** The user sent a message: show the latest turn now, and the turn it starts. */
  const followNextTurn = useCallback(() => {
    followNextTurnRef.current = true;
    const n = turnCountRef.current;
    if (n > 0) goToPage(n);
  }, [goToPage]);

  const retryTurn = useCallback((n: number) => {
    setTurnErrors((prev) => {
      const next = { ...prev };
      delete next[n];
      return next;
    });
  }, []);

  const fetchPage = useCallback(
    (n: number) => {
      const generation = generationRef.current;
      inFlightRef.current.add(n);
      requestTurn(socket, { page: n })
        .then((res) => {
          if (generation !== generationRef.current) return;
          setPageTurnId(n, res.turnId);
          if (!res.turn) throw new Error("This turn has no saved events yet.");
          const turn = backendTurnToFrontendTurn(res.turn);
          setThread((prev) =>
            prev.some((t) => t.id === turn.id) ? prev : [...prev, turn],
          );
        })
        .catch((err: Error) => {
          if (generation !== generationRef.current) return;
          setTurnErrors((prev) => ({ ...prev, [n]: err.message }));
        })
        .finally(() => {
          if (generation === generationRef.current) {
            inFlightRef.current.delete(n);
          }
        });
    },
    [socket, setThread, setPageTurnId],
  );

  // Keep the cache to the wanted turns and fetch the missing ones.
  useEffect(() => {
    if (!ready || page < 1) return;
    const visible = [page, page - 1, page + 1].filter(
      (n) => n >= 1 && n <= turnCount,
    );
    const keep = new Set(
      [...visible, ...recentPagesRef.current, turnCount]
        .map((n) => pageTurnIds[n])
        .filter((id): id is string => Boolean(id)),
    );
    setThread((prev) => {
      // Never drop a turn that is still running.
      const next = prev.filter(
        (t) => keep.has(t.id) || t.streaming || !t.completed,
      );
      return next.length === prev.length ? prev : next;
    });
    const loaded = new Set(thread.map((t) => t.id));
    for (const n of visible) {
      const id = pageTurnIds[n];
      if (
        !(id && loaded.has(id)) &&
        !inFlightRef.current.has(n) &&
        !turnErrors[n]
      ) {
        fetchPage(n);
      }
    }
  }, [
    ready,
    page,
    turnCount,
    pageTurnIds,
    thread,
    turnErrors,
    fetchPage,
    setThread,
  ]);

  return {
    turnCount,
    latestTurnId: turnCount > 0 ? pageTurnIds[turnCount] : undefined,
    pageTurnIds,
    page,
    ready,
    unseenLatest,
    turnErrors,
    goToPage,
    retryTurn,
    followNextTurn,
    reset,
    setInitialTurns,
    markReady,
    noteTurnStarted,
  };
}
