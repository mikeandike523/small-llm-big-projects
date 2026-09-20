# Plan: Release Manager (`./release_manager.py`) — v2

## What exists today

- **Versions**: backend version lives in root `package.json` (`"version"`), read live by
  `GET /api/version` (`http_api.py:429`). UI version is inlined at build time as
  `__APP_VERSION__` from `ui/package.json` by `ui/vite.config.ts`.
- **Display**: `ui/src/components/VersionWidget.tsx` shows both in the dashboard header
  (UI instantly via build constant, Backend via fetch).
- **Release notes**: nothing exists yet.

## Command

    release_manager.py bump <ui|backend> <major|minor|patch> <message...>

Behavior:
1. Bump the semver in the target `package.json` (root = backend, `ui/` = frontend)
   using the specified component (major/minor/patch).
2. Record the release entry (see layout below).
3. Print the new version.

## Release notes layout — one file per version + index

Notes live in a dedicated folder per target. Each release gets **its own file named
after its version** — this is deliberately per-version (not a single version.txt) so a
future changelog page can fetch a single version's notes on demand, and old files stay
immutable history.

    ./backend-release-notes/<VERSION>.txt      e.g. backend-release-notes/1.1.0.txt
    ./ui/public/ui-release-notes/<VERSION>.txt e.g. ui/public/ui-release-notes/0.2.0.txt

File content is the plain message for that version (a single entry; title optional —
see Open question 2). Example `backend-release-notes/1.1.0.txt`:

```
Add terminal page route
```

### `changelog-index.json`

Each notes folder also contains `changelog-index.json`, regenerated (rewritten whole)
on every bump — newest first:

```json
{
  "releases": [
    { "version": "1.1.0", "date": "2025-06-15", "file": "1.1.0.txt" },
    { "version": "1.0.1", "date": "2024-12-01", "file": "1.0.1.txt" }
  ]
}
```

- The index is derived from scanning the folder's `*.txt` files (sorted by the date
  recorded when each file was written) — so it can be rebuilt at any time and never
  drifts from what's on disk.
- Folder does not exist initially → created on first bump (git stays clean until a
  release is actually made).

## Runtime serving of UI release notes

- Anything in `ui/public/` is copied verbatim to `dist/` by Vite, so notes are plain
  static assets at runtime: `fetch("/ui-release-notes/changelog-index.json")` and
  `fetch("/ui-release-notes/<version>.txt")`. No API changes; works in the desktop
  app too (it serves the built SPA from the same backend).
- New module `ui/src/api/releaseNotes.ts`:

```ts
export type UiReleaseIndexEntry = { version: string; date: string; file: string };
export type UiReleaseNote = { version: string; date: string; message: string };

export function fetchUiReleaseIndex(): Promise<UiReleaseIndexEntry[]>   // index json
export function fetchUiReleaseNote(version): Promise<string>            // single file
export function fetchLatestUiReleaseNote(): Promise<{version, date, message} | null>
```

  Missing index (404 pre-first-release) → `[]` / `null`, must not error.

## UI display (VersionWidget)

- On mount, fetch the index once (cheap — tiny json). If non-empty, show the latest
  entry's message in the widget `title` tooltip and render a small "•" marker when
  the top version differs from `localStorage["slbp-last-seen-ui-release"]`
  (cleared once the widget/tooltip is seen).
- A future changelog page can reuse `fetchUiReleaseIndex()` +
  `fetchUiReleaseNote(v)` per entry — no schema change needed.

## Backend `/api/version` change (optional but recommended)

Read `./backend-release-notes/changelog-index.json`; if present, include the latest
release's version/date and message (read from its `<version>.txt`):

```python
return jsonify({"version": version, "note": latest_message or "", "note_date": ...})
```

One or two small file reads per request; cached in-process if we care later.

## release_manager.py implementation details

- Pure standard library: `argparse`, `json`, `re`, `datetime`, `pathlib`.
- Layout constants: `ROOT = Path(__file__).parent`,
  `BACKEND_NOTES_DIR = ROOT/"backend-release-notes"`,
  `UI_NOTES_DIR = ROOT/"ui/public/ui-release-notes"` (created with
  `mkdir(parents=True, exist_ok=True)`).
- Semver bump: parse `major.minor.patch` with a strict regex, fail loudly on
  non-semver versions rather than guessing. Refuse to bump to a version that already
  has a notes file in the target folder (idempotency guard).
- On bump:
  1. write `<newver>.txt` with the message,
  2. rescan folder → rewrite `changelog-index.json` atomically
     (temp file + `os.replace`) — index entries get the date of the new release and
     dates parsed from existing files (store date inside each entry; we derive it
     from file mtime or, more robustly, keep a `date` field recorded in the index
     and carried forward).
- `--dry-run` flag: prints what would change without writing.
- Targets case-insensitive (`ui` / `backend`); strict error otherwise.
- Exit codes: 0 success, 1 usage/validation error, 2 file error.

## Files touched

| File | Change |
|---|---|
| `release_manager.py` | **new** — CLI, version bump, per-version notes + index |
| `ui/src/api/releaseNotes.ts` | **new** — fetch/parse index + notes |
| `ui/src/components/VersionWidget.tsx` | fetch index, tooltip + "new release" marker |
| `src/ui_connector/.../http_api.py` | `/api/version` returns latest note (optional) |

## Open questions

1. Per-version files + `changelog-index.json` as described — good?
2. Should the `<version>.txt` file be just the message, or a small format like
   `Title\n\nBody` for richer changelog pages later?
3. Should the dashboard show a fuller "what's new" popup, or is tooltip/marker enough?
4. Include the backend note in `/api/version`?
5. Should `bump` also commit to git, or leave that to you?