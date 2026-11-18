# Plan: Static Artifacts

## Status

Planning only. This document records the initial artifact feature design. It does
not authorize or describe an implementation that has already been started.

The proxy-server library and internal architecture are intentionally left to the
implementer. The implementation should preserve the externally described
behavior and may choose the most suitable Node.js, Python, or hybrid design after
reviewing the existing project architecture and dependency constraints.

## Goal

Allow an agent to serve a directory as a browser-accessible artifact through the
SLBP gateway. The first version supports static directories only. It does not
proxy arbitrary localhost applications, run custom artifact backends, or support
WebSockets.

An artifact receives a permanent, opaque ID and a wildcard-host URL such as:

```text
https://<artifact-id>.<artifact-host>/
```

The artifact ID is generated when serving begins. IDs are never derived from the
directory name or contents and are never reused. Serving the same directory a
second time creates a new artifact ID.

## Runtime architecture

`slbp server run` starts the artifact-serving subsystem alongside the existing
UI, gateway, and Flask/SocketIO processes.

The implementation is expected to provide one internal static-artifact service
that can maintain multiple active artifact directories. The exact process and
library structure is an implementation choice. Possible implementations include
a single dynamic static server, a router with workers, or another design that
meets the requirements without unnecessarily exposing implementation details to
the tools.

The public artifact-serving listener must bind to localhost. The existing
host-side authenticated proxy and gateway remain responsible for public access
and wildcard-domain routing.

The artifact subsystem needs a private control interface for the Python tools.
It must not be reachable through public artifact URLs. A startup-generated secret
may protect this interface; the initial design does not require a named-pipe or
other specialized IPC transport.

The process/state integration should record the artifact service endpoint in the
existing server-state mechanism, including `.slbp-server.json` or its current
equivalent. Individual artifact records should not be encoded as fixed server
ports because their number is dynamic.

## Artifact lifecycle and persistence

Artifact metadata should be persisted so IDs remain permanently reserved and so
the system can distinguish active artifacts from retired ones.

An artifact record should include, at minimum:

- permanent artifact ID;
- owning session ID;
- served directory path;
- public URL;
- creation timestamp;
- stopped timestamp, when applicable;
- active/stopped status.

Active artifact routing may be held in memory, but the database is the source of
truth for ownership, historical IDs, and lifecycle state.

Stopping an artifact removes it from active routing but does not delete its
historical record or recycle its ID. Requests to a deliberately stopped artifact
should return `410 Gone`.

Artifacts are session-scoped. Listing and management operations should not expose
artifacts belonging to other sessions. Server-wide cleanup, expiration, or cron
jobs are separate future concerns.

## Agent tools

### `serve_dir`

Description:

> Serve a directory as an artifact in the background.

The tool should:

1. Validate and resolve the requested directory according to the existing
   session filesystem rules.
2. Apply the same approval semantics as a write operation.
3. Allocate a new permanent artifact ID.
4. Register the directory with the artifact service.
5. Wait until serving is ready.
6. Return the artifact ID, public URL, directory, status, and useful metadata.

The tool must not automatically open the artifact. Creation and presentation are
separate actions so the agent does not confuse serving a result with displaying
it.

Serving a directory inside the session workspace may be automatically accepted
when the session is configured for auto-accepted edits. In default approval mode,
serving requires human approval. Paths outside the normal session scope should
follow the existing out-of-scope/write approval behavior.

Symlinks and junctions should follow ordinary operating-system behavior for the
initial version. The implementation should avoid adding a separate, overly
complicated link-resolution policy unless existing filesystem safeguards require
one.

### `open_artifact`

Accept an artifact ID or artifact URL and request that the user interface display
it.

- In the browser UI, open the artifact viewer containing an iframe.
- In the desktop app, open an artifact `WebContentsView`.
- In a context without a viewer, return the URL or a clear unavailable-viewer
  result without treating artifact creation as failed.

This tool should use the existing UI/IPC capability detection pattern used by
tools such as `open_in_terminal`.

### `list_artifacts`

Return currently active artifacts owned by the current session. Each entry should
include its ID, URL, directory, display information if available, creation time,
and serving status.

Stopped artifacts are not included in the initial list operation because this
tool is intended to show what is currently being served.

### `stop_serving_dir`

Stop an active artifact by ID. The operation should remove active routing,
preserve the permanent artifact record, and cause subsequent requests to return
`410 Gone`.

The implementation may use an internal name such as `stop_artifact`, but the
agent-facing name should remain understandable and consistent with `serve_dir`.

### Optional future tool: `get_artifact`

A future query tool may inspect one artifact, including a stopped artifact, for
diagnostics or history. It is not required for the first implementation if
`list_artifacts` and tool return values provide sufficient information.

## Static HTTP behavior

The first artifact server supports static directories only.

Required behavior:

- serve `index.html` automatically when present;
- support ordinary relative asset URLs;
- support root-relative asset URLs through the wildcard artifact hostname;
- preserve query strings;
- prevent path traversal outside the registered directory;
- reject WebSocket upgrades;
- do not proxy arbitrary localhost ports;
- do not forward cookies or arbitrary request headers to another service;
- bind internal listeners to localhost;
- return `410 Gone` for stopped artifact IDs;
- return an appropriate not-found response for never-registered IDs.

When a requested directory has no `index.html`, the initial behavior should be
Apache-style directory listing. Listings must escape displayed filenames, encode
links safely, provide useful parent-directory navigation, and never expose the
server's filesystem path.

The implementer should verify that the chosen static middleware supports the
required directory-listing behavior. If it does not, add a narrow listing layer
around it or choose a better-suited static-serving library. This is an
implementation decision, not a change to the product requirement.

## Gateway routing

The gateway should add a host-based rule for the configured artifact domain:

```text
<artifact-id>.<artifact-host> -> artifact service
```

The gateway must validate the hostname pattern and preserve enough host
information for the artifact service to identify the artifact. It must not treat
arbitrary hostname text as a filesystem path or target address.

Normal UI, API, and webhook routing must remain unchanged. The artifact route
must be evaluated before the ordinary UI fallback.

## Browser UI

Add an artifact viewer to the browser UI. It should contain:

```text
[ artifact URL                                      ] [copy]
[                                                   ]
[                     iframe                        ]
```

The copy control copies the canonical public artifact URL. The iframe loads the
wildcard-host URL directly.

The viewer is opened by an explicit UI event associated with `open_artifact`.
Serving an artifact alone must not unexpectedly replace the current session UI.

## Desktop UI

Add artifact viewing through a desktop `WebContentsView`, using the existing
desktop IPC bridge and tab/view management patterns.

The initial implementation may model artifacts as a separate desktop tab kind or
as another suitable view managed by the current desktop shell. It should preserve
the ability to switch back to the session while keeping the artifact available.

## System-prompt guidance

Add a brief section to the system prompt explaining that:

- `serve_dir` is the standard way to present a static directory;
- `open_artifact` is separate and should be called when the user should see the
  result;
- `list_artifacts` reports active artifacts for the current session;
- `stop_serving_dir` cleans up an active artifact;
- artifact IDs are permanent and are never reused;
- artifacts are session-scoped;
- static sites should prefer relative asset paths;
- the first version does not support WebSockets or custom localhost services.

## Security and approval requirements

- Public access is expected to be protected by the external authenticated proxy,
  but the artifact service must still reject unknown and inactive artifact IDs.
- Internal listeners bind to localhost only.
- The management/control interface is separate from public artifact traffic and
  protected by the startup secret.
- No cookies or arbitrary headers are forwarded to another service in this
  static-only version.
- Artifact directories are subject to write-like approval semantics.
- Directory listings must not reveal absolute filesystem paths.
- Artifact IDs must be opaque and strictly validated.
- The artifact server must not support arbitrary target hosts or ports yet.

## Suggested validation

The implementation should include tests for:

- artifact ID generation and non-reuse;
- session ownership and cross-session access rejection;
- serving an index file;
- serving nested files and root-relative URLs;
- directory listings and HTML escaping;
- query-string preservation;
- traversal attempts;
- symlink/junction behavior on supported platforms;
- stopped artifacts returning `410 Gone`;
- unknown artifact IDs;
- WebSocket rejection;
- control-interface authentication;
- process startup and shutdown integration;
- browser viewer URL/copy behavior;
- desktop `open_artifact` IPC behavior.

## Non-goals for the first version

- arbitrary localhost proxying;
- custom backend servers;
- WebSocket support;
- cookies or header forwarding;
- per-artifact authentication beyond the outer deployment proxy;
- artifact sharing across sessions;
- automatic artifact opening after `serve_dir`;
- automatic expiration or server-wide cleanup jobs;
- artifact IDs based on directory names or content hashes.
