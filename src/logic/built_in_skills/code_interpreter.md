## Skill: Code Interpreter

Use `code_interpreter` to run Python in a sandboxed environment (Piston/Docker).
The sandbox is ephemeral — nothing persists to the host after the call.
Write code as a normal executable script; use a `if __name__ == "__main__":` guard.
Returns stdout on success. Returns a string starting with `FAILED:` on non-zero exit.

### Passing the Code

Inline (short scripts, one-offs):

```json
{
  "code": { "source": "raw", "value": "if __name__ == '__main__':\n    print('hello')" }
}
```

From session memory (when the script is too long to inline, or was built up incrementally):

```json
{
  "code": { "source": "session_memory", "key": "my_script" }
}
```

### Passing Arguments

Arguments arrive in the script as `sys.argv[1]`, `sys.argv[2]`, etc.
Each arg entry is a `{source, value|key}` object — the same shape as `code`.

Raw values (any JSON type — strings pass through, everything else is JSON-serialised):

```json
{
  "args": [
    { "source": "raw", "value": "hello" },
    { "source": "raw", "value": 42 },
    { "source": "raw", "value": [1, 2, 3] }
  ]
}
```

The script receives: `sys.argv[1] == "hello"`, `sys.argv[2] == "42"`, `sys.argv[3] == "[1, 2, 3]"`.

From session memory (pass a large blob — e.g. JSON data — stored in memory directly to the script):

```json
{
  "args": [
    { "source": "session_memory", "key": "input_data" }
  ]
}
```

### Capturing Output

Default: stdout is returned inline as the tool result.

To write stdout directly into session memory (useful when the output is large or will feed another tool):

```json
{
  "target": "session_memory",
  "target_session_memory_key": "result"
}
```

### Full Example — JSON Transform

```json
{
  "code": {
    "source": "raw",
    "value": "import sys, json\n\nif __name__ == '__main__':\n    data = json.loads(sys.argv[1])\n    out = [x * 2 for x in data]\n    print(json.dumps(out))"
  },
  "args": [
    { "source": "session_memory", "key": "input_list" }
  ],
  "target": "session_memory",
  "target_session_memory_key": "doubled_list"
}
```

### Handling Failure

When the script exits non-zero, the result starts with `FAILED:` and includes the exit code,
stderr, and stdout. Inspect the stderr for the traceback to diagnose the problem.
Set `enable_tracebacks: false` to strip the traceback and show only the final exception line
(saves context when the error is already obvious).

### When NOT to Use

- To run shell commands, use `host_shell` instead.
- To write a file that persists on the host, write it to the global workspace
  (`get_global_workspace_dir`) using `write_text_file`, not from inside the sandbox.
- The sandbox has no network access and no access to project files — do not attempt to read
  project source inside the interpreter.
