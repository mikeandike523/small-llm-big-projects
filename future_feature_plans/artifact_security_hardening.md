# Artifact security and serving hardening

The initial artifact implementation is intentionally a demonstration-oriented
static server. It binds the artifact service to localhost and relies on the
host-side authenticated proxy for public access. The following safeguards are
now part of the baseline:

- `ARTIFACT_MAX_FILE_BYTES` limits the size of an individual response.
- `ARTIFACT_MAX_DIRECTORY_ENTRIES` limits generated directory listings.
- `ARTIFACT_SERVE_TIMEOUT_MS` limits the lifetime of a public artifact request.
- ETags are metadata-based and do not hash file contents.

The current design intentionally permits symlinks and junctions to behave like
the underlying operating system. A future hardening mode could instead require
the resolved target to remain below the registered artifact root. Any such
change would need to be explicit because it would alter the current symlink
behavior.

There is also a normal filesystem time-of-check/time-of-use race: a file can be
replaced after validation and before it is opened. Future options include
opening a validated file descriptor and serving through that descriptor,
rechecking the descriptor's metadata before streaming, or moving artifact
streaming into the host-side trusted server. The last option is the intended
long-term separation: the VM should retain only a narrow control interface,
while the host-side session server enforces authentication, path boundaries,
quotas, and streaming policy.

Future limits worth considering include aggregate artifact-size quotas,
concurrent-download limits, response bandwidth limits, stricter MIME policy,
and a maximum number of active artifacts per session.
