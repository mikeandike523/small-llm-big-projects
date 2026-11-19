# Skill: Designing Static Artifacts

Use this guide when the user asks you to build a visual website, demo, report,
dashboard, presentation, or other browser-viewable artifact.

## Choose the simplest suitable build strategy

- For a small self-contained result, use plain `index.html`, CSS, and browser
  JavaScript. Keep assets in nearby `assets/`, `styles/`, or `scripts/`
  directories and verify that every reference works from the served root.
- For a component-based application, use the project's existing Vite setup when
  one exists. Build the production bundle and serve `dist/`, not the source
  directory and not the Vite development server.
- For a static-site generator such as Astro, Eleventy, Hugo, or a similar tool,
  run its production build and serve the generated output directory (often
  `dist/`, `build/`, or `public/`). Do not serve the generator's source tree
  unless the user explicitly asks to show source files.
- Use a framework only when it improves the result. A static artifact cannot
  rely on a backend process, WebSocket connection, cookie, or arbitrary
  localhost service.

## Build and validate before presenting

1. Identify the actual production output directory.
2. Run the project's build command and fix build errors before serving.
3. Confirm that the output contains an entry page, normally `index.html`.
4. Check asset paths, case sensitivity, fonts, images, and browser console
   assumptions. Prefer relative paths or root-relative paths that work from the
   artifact origin.
5. Call `serve_dir` on the output directory, not the project root when that
   would expose source, configuration, dependencies, or build caches.
6. Call `open_artifact` explicitly after serving when the user should see the
   result. `serve_dir` does not open a viewer automatically.

## Paths and routing

Artifact URLs are served from the root of a dedicated wildcard origin. A
reference such as `/assets/logo.svg` therefore resolves at the artifact root.
Relative references such as `assets/logo.svg` are usually the most portable.
If using a `<base>` element, use it deliberately and verify nested-page links;
`<base href="/">` makes relative references resolve from the artifact root but
can change the meaning of every relative link and form action.

The initial artifact server is static-only. It does not provide server-side
rendering, API routes, WebSockets, or proxying to a local development server.
For an SPA that needs clean client-side routes, pass
`rewrite_rule="SPA_INDEX"` to `serve_dir`. This is the only approved rewrite:
missing routes (and directories without their own index) fall back to the
artifact root's `index.html`; existing files are still served normally. Use it
only when the output contains a valid SPA entry page. Otherwise prefer hash-
based client routing, generate real HTML pages for deep links, or ensure that
the generated site only navigates to files that exist in the output directory.

## Updating and presenting an artifact

- If source files change, rebuild the production output before serving again.
- Calling `open_artifact` again refreshes the in-app viewer. The artifact URL
  remains stable, so independent viewers should use a normal reload; if an
  older resource remains visible, tell the user to hard-refresh with
  Ctrl+Shift+R.
- Use `list_artifacts` to find active artifacts in the current session and
  `stop_serving_dir` when an artifact is no longer needed. Stopped artifact IDs
  are not reused.
- Tell the user the artifact URL and what was served when handing off the
  result. Mention any known limitations, such as static-only behavior or a
  missing interactive backend.

## Quality bar

Make the artifact feel intentional: establish a clear visual hierarchy, use
responsive layout, provide readable contrast and useful empty/error states,
avoid placeholder content when real content is available, and keep the first
screen understandable without explanation. Treat the generated output as the
deliverable: source code alone is not a successfully presented artifact.
