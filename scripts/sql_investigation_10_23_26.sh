#!/usr/bin/env bash
# Read-only investigation (2026-10-23): `slbp intense-migration run
# fill-session-cache` indexed only ~425 turns of a session that showed 4000+
# pages, and the session's latest message was missing after the migration.
#
# Every statement below is a SELECT; nothing is written.
#
# Usage:
#   bash scripts/sql_investigation_10_23_26.sh                # list the largest sessions
#   bash scripts/sql_investigation_10_23_26.sh <session_id>   # full report for one session
#   bash scripts/sql_investigation_10_23_26.sh <session_id> > report.txt 2>&1
#
# Credentials come from server/run_sql.sh (MYSQL_DATABASE / MYSQL_USER /
# MYSQL_PASSWORD env vars, with its defaults).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SQL="$REPO_ROOT/server/run_sql.sh"

run() {
	echo
	echo "=== $1 ==="
	bash "$RUN_SQL" -q -c "$2" || echo "(query failed, continuing)"
}

if [[ $# -eq 0 ]]; then
	run "Sessions by turn_started events (top 15)" "
SELECT e.session_id,
       COUNT(*) AS turn_started_events,
       m.turn_count AS meta_turn_count,
       m.history_cache_compatible AS cache_ok,
       (SELECT COUNT(*) FROM chat_turn_index t WHERE t.session_id = e.session_id) AS indexed_turns
FROM session_events e
LEFT JOIN session_meta m ON m.session_id = e.session_id
WHERE e.event_type = 'turn_started'
GROUP BY e.session_id, m.turn_count, m.history_cache_compatible
ORDER BY turn_started_events DESC
LIMIT 15;"
	echo
	echo "Re-run with the session id of the affected session for the full report."
	exit 0
fi

SID="$1"
if [[ ! "$SID" =~ ^[A-Za-z0-9_.:-]+$ ]]; then
	echo "Session id contains unexpected characters: $SID" >&2
	exit 2
fi
S="'$SID'"

run "1. session_meta row" "
SELECT session_id, schema_version, turn_count, task_title_count,
       history_cache_compatible, corrupt, FROM_UNIXTIME(created_at) AS created,
       updated_at
FROM session_meta WHERE session_id = $S;"

run "2. Events by type (count, id range, time range, payload MB)" "
SELECT event_type, COUNT(*) AS n, MIN(id) AS first_id, MAX(id) AS last_id,
       MIN(created_at) AS first_at, MAX(created_at) AS last_at,
       ROUND(SUM(LENGTH(payload)) / 1048576, 2) AS payload_mb
FROM session_events WHERE session_id = $S
GROUP BY event_type ORDER BY n DESC;"

run "3. turn_started events vs distinct turn ids" "
SELECT COUNT(*) AS turn_started_events,
       COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id'))) AS distinct_turn_ids,
       SUM(JSON_EXTRACT(payload, '$.turn_id') IS NULL) AS missing_turn_id
FROM session_events WHERE session_id = $S AND event_type = 'turn_started';"

run "4. subturn_started events vs distinct subturn ids / turn ids" "
SELECT COUNT(*) AS subturn_started_events,
       COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.subturn_id'))) AS distinct_subturn_ids,
       COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id'))) AS distinct_parent_turn_ids
FROM session_events WHERE session_id = $S AND event_type = 'subturn_started';"

run "5. Most repeated turn ids in turn_started (top 20)" "
SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id')) AS turn_id,
       COUNT(*) AS times, MIN(id) AS first_id, MAX(id) AS last_id,
       MIN(created_at) AS first_at, MAX(created_at) AS last_at
FROM session_events WHERE session_id = $S AND event_type = 'turn_started'
GROUP BY turn_id HAVING times > 1
ORDER BY times DESC, first_id LIMIT 20;"

run "6. Distribution: how many turn ids were started N times" "
SELECT times, COUNT(*) AS turn_ids FROM (
  SELECT COUNT(*) AS times
  FROM session_events WHERE session_id = $S AND event_type = 'turn_started'
  GROUP BY JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id'))
) x GROUP BY times ORDER BY times;"

run "7. Turns with the most subturns (top 20; collisions would show here)" "
SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id')) AS turn_id,
       COUNT(*) AS subturn_events,
       COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.subturn_id'))) AS distinct_subturns,
       MIN(id) AS first_id, MAX(id) AS last_id,
       MIN(created_at) AS first_at, MAX(created_at) AS last_at
FROM session_events WHERE session_id = $S AND event_type = 'subturn_started'
GROUP BY turn_id ORDER BY distinct_subturns DESC LIMIT 20;"

run "8. Most repeated subturn ids (top 10)" "
SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.subturn_id')) AS subturn_id,
       COUNT(*) AS times, MIN(id) AS first_id, MAX(id) AS last_id
FROM session_events WHERE session_id = $S AND event_type = 'subturn_started'
GROUP BY subturn_id HAVING times > 1
ORDER BY times DESC LIMIT 10;"

run "9. session_created events (more than one = re-emitted session)" "
SELECT id, created_at,
       JSON_EXTRACT(payload, '$.schema_version') AS schema_version,
       JSON_EXTRACT(payload, '$.created_at') AS created_epoch
FROM session_events WHERE session_id = $S AND event_type = 'session_created'
ORDER BY id;"

run "10. turn_started events per day" "
SELECT DATE(created_at) AS day, COUNT(*) AS turn_started,
       COUNT(DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id'))) AS distinct_turns
FROM session_events WHERE session_id = $S AND event_type = 'turn_started'
GROUP BY day ORDER BY day;"

run "11. chat_turn_index summary" "
SELECT COUNT(*) AS rows_, MIN(turn_seq) AS min_seq, MAX(turn_seq) AS max_seq,
       MIN(start_event_id) AS min_start, MAX(start_event_id) AS max_start,
       SUM(completed) AS completed
FROM chat_turn_index WHERE session_id = $S;"

run "12. chat_turn_index: last 5 turns" "
SELECT turn_seq, turn_id, start_event_id, completed, LEFT(title, 60) AS title
FROM chat_turn_index WHERE session_id = $S
ORDER BY turn_seq DESC LIMIT 5;"

run "13. chat_history_cache summary + subturns per turn (top 10)" "
SELECT COUNT(*) AS rows_, COUNT(DISTINCT turn_seq) AS turns,
       MAX(subturn_seq) AS max_subturn_seq
FROM chat_history_cache WHERE session_id = $S;
SELECT turn_seq, COUNT(*) AS subturns
FROM chat_history_cache WHERE session_id = $S
GROUP BY turn_seq ORDER BY subturns DESC LIMIT 10;"

run "14. turn_started events whose turn id is NOT in chat_turn_index (count + first 10)" "
SELECT COUNT(*) AS not_indexed
FROM session_events e
LEFT JOIN chat_turn_index t
  ON t.session_id = e.session_id
 AND t.turn_id = JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.turn_id'))
WHERE e.session_id = $S AND e.event_type = 'turn_started' AND t.turn_id IS NULL;
SELECT e.id, e.created_at, JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.turn_id')) AS turn_id
FROM session_events e
LEFT JOIN chat_turn_index t
  ON t.session_id = e.session_id
 AND t.turn_id = JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.turn_id'))
WHERE e.session_id = $S AND e.event_type = 'turn_started' AND t.turn_id IS NULL
ORDER BY e.id LIMIT 10;"

run "15. Events after the last indexed turn start, by type" "
SELECT event_type, COUNT(*) AS n, MIN(id) AS first_id, MAX(id) AS last_id
FROM session_events
WHERE session_id = $S
  AND id >= (SELECT COALESCE(MAX(start_event_id), 0) FROM chat_turn_index WHERE session_id = $S)
GROUP BY event_type ORDER BY first_id;"

run "16. Newest 25 events (no payload bodies)" "
SELECT id, created_at, event_type,
       JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id')) AS turn_id,
       JSON_UNQUOTE(JSON_EXTRACT(payload, '$.subturn_id')) AS subturn_id,
       JSON_EXTRACT(payload, '$.index') AS ex_index,
       LEFT(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.user_text')), 80) AS user_text,
       LENGTH(payload) AS bytes
FROM session_events WHERE session_id = $S
ORDER BY id DESC LIMIT 25;"

run "17. Newest 10 subturn_started (where did the latest user messages land?)" "
SELECT e.id, e.created_at,
       JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.turn_id')) AS turn_id,
       t.turn_seq AS indexed_turn_seq,
       JSON_EXTRACT(e.payload, '$.is_continuation') AS is_cont,
       JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.origin')) AS origin,
       LEFT(JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.user_text')), 80) AS user_text
FROM session_events e
LEFT JOIN chat_turn_index t
  ON t.session_id = e.session_id
 AND t.turn_id = JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.turn_id'))
WHERE e.session_id = $S AND e.event_type = 'subturn_started'
ORDER BY e.id DESC LIMIT 10;"

run "18. Other sessions sharing turn ids with this one (count)" "
SELECT COUNT(DISTINCT o.session_id) AS other_sessions, COUNT(*) AS shared_turn_started
FROM session_events o
JOIN (
  SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.turn_id')) AS turn_id
  FROM session_events WHERE session_id = $S AND event_type = 'turn_started'
) mine ON mine.turn_id = JSON_UNQUOTE(JSON_EXTRACT(o.payload, '$.turn_id'))
WHERE o.event_type = 'turn_started' AND o.session_id <> $S;"
