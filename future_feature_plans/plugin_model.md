# Plugin Model for Skills and Tools

## Background

Today, SLBP loads custom skills, custom tools, and startup tool calls through
three related but separate mechanisms:

- `skills/` provides markdown skill guides and `skills.json` metadata.
- `tools/` provides Python custom tool plugins, with tool names prefixed by
  each plugin's `TOOL_NAMESPACE`.
- `startup_tool_calls.json` is a session-level list of tool calls. It is not
  attached to a skill or tool plugin, and callers must use the final prefixed
  tool names such as `mydataplugin_schema`.

This is acceptable for now, but it does not model a product/plugin as one
cohesive unit. A database platform integration, for example, naturally wants
its skills, tools, metadata, and optional activation behavior grouped together.

## Proposed Model

Introduce a first-class plugin model. Each plugin should live in one folder
with a manifest and its related skill files and tools.

Example:

```text
plugins/
  mydataplugin/
    plugin.json
    skills/
      overview.md
      querying.md
      writes.md
    tools/
      __init__.py
      schema.py
      query.py
      write_record.py
```

The orchestrator should discover all plugin manifests, build a plugin registry,
respect manifest-level autoload settings, and then decide which plugins to
enable for a user request. Enabling a plugin would make both its skill guidance
and its tools available for that turn.

## Manifest Sketch

```json
{
  "id": "mydataplugin",
  "name": "My Data Plugin",
  "blurb": "Interact with the database-powered data platform.",
  "autoload": false,
  "skills": [
    {
      "id": "overview",
      "file": "skills/overview.md",
      "dependencies": ["querying"]
    },
    {
      "id": "querying",
      "file": "skills/querying.md",
      "dependencies": []
    },
    {
      "id": "writes",
      "file": "skills/writes.md",
      "dependencies": ["querying"]
    }
  ],
  "tools": {
    "namespace": "mydataplugin",
    "path": "tools"
  }
}
```

Open design questions:

- Whether plugin activation should always load all plugin skills, or allow the
  selector to choose a subset of skills within the enabled plugin.
- Whether plugin activation should expose all plugin tools, or allow a narrower
  per-turn tool subset.
- Whether plugin dependencies should exist in addition to skill dependencies.

## Startup/Activation Calls

Current startup tool calls should remain understood as session-level behavior,
not plugin-level behavior. They are not tied to the current skills/tools loading
system, and they already need to call tools by their final namespaced names.

Later, if needed, add plugin activation calls. These would be declared in the
plugin manifest and run when a plugin is activated, usually once per full user
turn rather than once per subturn. This could support actions such as loading a
database schema snapshot, checking connection health, or refreshing a project
index before the agent uses the plugin.

Sketch:

```json
{
  "activation_tool_calls": [
    {
      "name": "mydataplugin_schema",
      "args": {
        "include_tables": true
      },
      "run": "once_per_turn"
    }
  ]
}
```

These calls should be treated as plugin activation hooks, not as replacements
for session startup calls.
