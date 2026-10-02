/**
 * One turn per page: the turn list, the current page and the turn cache.
 *
 * `thread` (owned by useSocketWiring) is the cache of loaded turns, in no
 * particular order; live socket handlers update turns in it by id. This hook
 * decides what the cache holds:
 *
 *   - the latest turn, always (live events keep updating it);
 *   - the current page's turn and its previous/next neighbors (prefetched);
 *   - the last RECENT_TURNS_KEPT visited turns.
 *
 * Everything else is evicted when the page changes. Missing turns are fetched
 * with `load_turn {turnId}`. The current page is mirrored to `?turn=N` so a
 * reload keeps the reader's place.
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

const RECENT_TURNS_KEPT = 5;

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
  const [turnIds, setTurnIdsState] = useState<string[]>([]);
  // 1-based page number; 0 while there is no turn to show.
  const [page, setPageState] = useState(0);
  const [ready, setReady] = useState(false);
  // A turn started (or the latest was followed up) while another page showed.
  const [unseenLatest, setUnseenLatest] = useState(false);
  const [turnErrors, setTurnErrors] = useState<Record<string, string>>({});

  // Refs mirror the state so socket handlers read current values.
  const turnIdsRef = useRef<string[]>([]);
  const pageRef = useRef(0);
  const readyRef = useRef(false);
  const recentRef = useRef<string[]>([]);
  const inFlightRef = useRef(new Set<string>());
  // Bumped on reset so responses to an earlier connection are ignored.
  const generationRef = useRef(0);
  // Set when the user sends a message: show the turn it starts.
  const followNextTurnRef = useRef(false);

  const setTurnIds = useCallback((ids: string[]) => {
    turnIdsRef.current = ids;
    setTurnIdsState(ids);
  }, []);

  const goToPage = useCallback((n: number) => {
    const ids = turnIdsRef.current;
    if (!Number.isInteger(n) || n < 1 || n > ids.length) return;
    pageRef.current = n;
    setPageState(n);
    const id = ids[n - 1];
    recentRef.current = [
      ...recentRef.current.filter((x) => x !== id),
      id,
    ].slice(-RECENT_TURNS_KEPT);
    if (n === ids.length) setUnseenLatest(false);
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
    setTurnIds([]);
  }, [setTurnIds]);

  /**
   * The latest-turn load finished: show the page we were on (reconnect), else
   * the URL's `?turn=N` (first load), else the latest turn.
   */
  const markReady = useCallback(() => {
    readyRef.current = true;
    setReady(true);
    const n = turnIdsRef.current.length;
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
      const isNew = !turnIdsRef.current.includes(turnId);
      if (isNew) setTurnIds([...turnIdsRef.current, turnId]);
      if (!readyRef.current) return;
      const index = turnIdsRef.current.indexOf(turnId) + 1;
      if (followNextTurnRef.current || pageRef.current === 0) {
        followNextTurnRef.current = false;
        goToPage(index);
      } else if (pageRef.current !== index) {
        // A new turn, or a follow-up to the latest one, on another page.
        setUnseenLatest(true);
      }
    },
    [goToPage, setTurnIds],
  );

  /** The user sent a message: show the latest turn now, and the turn it starts. */
  const followNextTurn = useCallback(() => {
    followNextTurnRef.current = true;
    const n = turnIdsRef.current.length;
    if (n > 0) goToPage(n);
  }, [goToPage]);

  const retryTurn = useCallback((turnId: string) => {
    setTurnErrors((prev) => {
      const next = { ...prev };
      delete next[turnId];
      return next;
    });
  }, []);

  const fetchTurn = useCallback(
    (turnId: string) => {
      const generation = generationRef.current;
      inFlightRef.current.add(turnId);
      requestTurn(socket, { turnId })
        .then((res) => {
          if (generation !== generationRef.current) return;
          if (!res.turn) throw new Error("This turn has no saved events yet.");
          const turn = backendTurnToFrontendTurn(res.turn);
          setThread((prev) =>
            prev.some((t) => t.id === turnId) ? prev : [...prev, turn],
          );
        })
        .catch((err: Error) => {
          if (generation !== generationRef.current) return;
          setTurnErrors((prev) => ({ ...prev, [turnId]: err.message }));
        })
        .finally(() => {
          if (generation === generationRef.current) {
            inFlightRef.current.delete(turnId);
          }
        });
    },
    [socket, setThread],
  );

  // Keep the cache to the wanted turns and fetch the missing ones.
  useEffect(() => {
    if (!ready || page < 1) return;
    const visible = [page, page - 1, page + 1]
      .filter((n) => n >= 1 && n <= turnIds.length)
      .map((n) => turnIds[n - 1]);
    const keep = new Set([
      ...visible,
      ...recentRef.current,
      turnIds[turnIds.length - 1],
    ]);
    setThread((prev) => {
      // Never drop a turn that is still running.
      const next = prev.filter(
        (t) => keep.has(t.id) || t.streaming || !t.completed,
      );
      return next.length === prev.length ? prev : next;
    });
    const loaded = new Set(thread.map((t) => t.id));
    for (const id of visible) {
      if (!loaded.has(id) && !inFlightRef.current.has(id) && !turnErrors[id]) {
        fetchTurn(id);
      }
    }
  }, [ready, page, turnIds, thread, turnErrors, fetchTurn, setThread]);

  return {
    turnIds,
    page,
    ready,
    unseenLatest,
    turnErrors,
    goToPage,
    retryTurn,
    followNextTurn,
    reset,
    setInitialTurnIds: setTurnIds,
    markReady,
    noteTurnStarted,
  };
}
