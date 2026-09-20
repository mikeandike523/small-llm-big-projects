# Plan — UI (web) + Backend changelog tooltips & "view all" dialogs

Follow-up to the desktop implementation (done). Now the web UI (`ui/`) and the
backend get the same treatment: latest-note tooltip on the version widget and a
"view all changelogs" dialog per side, with async note loading after the index.

## Current state (verified)

- `ui/public/ui-release-notes/` — UI changelogs (index + per-version files),
  served by Vite as static assets at `/ui-release-notes/...`. Already fetched by
  `ui/src/api/releaseNotes.ts` (`fetchUiReleaseIndex`, `fetchUiReleaseNote`,
  `useLatestUiReleaseNote` hook) — UI side needs NO new backend routes.
- `backend-release-notes/` — backend changelogs on disk. `/api/version`
  (`http_api.py`) already reads the **latest** note and returns
  `{version, note, note_date}`. It resolves paths via
  `Path(__file__).parents[3]` — a fixed upward count, not a real repo-root walk.
- `VersionWidget.tsx` shows UI/Backend versions with a combined hover tooltip
  (already includes latest UI + backend notes) and the unseen-release "•" marker.

## Changes

### 1. UI side (tooltip already exists; add button + dialog)

- **`VersionWidget.tsx`**:
  - Add a small "Changelogs" button next to the widget values (two lines get one
    button? — no: **two separate buttons** is cleaner:
    a tiny `UI` changelog button and a tiny `Backend` one, styled like the
    desktop health page's button, on each row).
  - Clicking opens a new `ChangelogDialog` component for that side.
- **New `ui/src/components/ChangelogDialog.tsx`** (mirrors the desktop dialog):
  - HTML `<dialog>` via `useRef` + `showModal()`, close on ✕ / backdrop / Esc.
  - On open: fetch the index for the chosen side, render one section per
    release immediately (`version`, `date`, note body = `…` placeholder), then
    kick off each per-version note fetch **independently** — each fills its own
    section as it arrives (async after index, like desktop).
  - Empty state: "No releases recorded yet."
- **`ui/src/api/releaseNotes.ts`**: generalize — rename/add
  `fetchReleaseIndex(side: "ui" | "backend")` and
  `fetchReleaseNote(side, version)`:
  - `ui` → `/ui-release-notes/...` (static, unchanged behavior)
  - `backend` → new `/api/changelog` routes (below)
  - Keep existing exports as thin wrappers so current imports still work.
- **Shared styles** for dialog + buttons in `ui/src/css/*` matching the app's
  dark theme.

### 2. Backend: new routes + repo-root resolution fix

- **New helper module `src/ui_connector/release_notes.py`** (separate file to
  avoid bloating `http_api.py`; no circular-import risk since it imports nothing
  from ui_connector):
  - `find_repo_root_from(start: Path) -> Path | None` — walk up from `start`
    (normally `Path(__file__).resolve()`) until a `.git` directory is found;
    stop when `dir.parent == dir` (drive/filesystem root) or on `OSError`
    (permission error ends traversal). **No arbitrary depth cap.**
  - `notes_dir` = `<repo_root>/backend-release-notes`
  - `read_index() -> list[ReleaseEntry]`, `read_note(version) -> str | None`
    (version sanitized: only `[A-Za-z0-9._-]` allowed before joining the path),
    plus `latest_note()` reused by `/api/version`.
- **Routes in `http_api.py`**:
  - `GET /api/changelog` → `{"releases": [{version, date, file}, ...]}` from
    `changelog-index.json` (empty list when absent).
  - `GET /api/changelog/<version>` → `{"version", "date", "message"}` or 404.
- **Refactor `/api/version`**: `_latest_backend_release_note()` moves to
  `release_notes.py` and now uses the repo-root walk instead of the hardcoded
  `parents[3]` (and the same walk replaces the root `package.json` lookup).

### 3. Correctness notes

- Backend path resolution is `__file__`-anchored with the `.git` walk — never
  cwd, never a fixed parent count.
- Both dialogs load notes per-version asynchronously after the index fetch;
  a slow/failed note fetch only leaves that one section as `…`.
- UI changelog still works in the desktop app unchanged (static assets served
  by the backend); backend changelog routes work anywhere the server runs.

## Files touched

- `ui/src/components/VersionWidget.tsx` (buttons + wiring)
- `ui/src/components/ChangelogDialog.tsx` (new)
- `ui/src/api/releaseNotes.ts` (generalize to both sides)
- `ui/src/css/...` (dialog/button styles)
- `src/ui_connector/release_notes.py` (new)
- `src/ui_connector/socket_handler_components/http_api.py` (2 routes + refactor)

## Open question

Should the two buttons be per-row (one for UI, one for Backend — my
recommendation, matches "both should have separate view all buttons") or a
single button that shows both changelogs in one dialog?
