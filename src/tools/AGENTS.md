# AGENTS.md

## Role

Tool definition registration and execution. One backend today, the console registry, driven by [../control_loop.py](../control_loop.py): construct → `tool_define()` into `start_stream` → `tool_run()` per call.

## Constraints & protocols

- **The registry stores the neutral shape, never a provider's wire shape** — `{name, description, parameters}`. Turning it into wire shapes is the wrapper layer's job ([../llm/](../llm/)); don't pre-convert here.
- **`impls` keys must match the `name`s in `tools`.** A mismatch raises only inside `tool_run`.
- **`tool_run` takes `arguments` as a JSON string**, already unified by the wrapper's `tool_call_arguments()`.
- **The return value is `json.dumps`'d** (with `ensure_ascii=False`): return a JSON-serializable value and let `tool_run` serialize it — don't pre-serialize.
- **`tool_run` converts ordinary tool errors (`Exception`) into error text for the model and never re-raises them** — a bad name, bad JSON, a bad signature, or the tool raising. `BaseException` subclasses (`KeyboardInterrupt`, `SystemExit`) still propagate, so Ctrl-C stays in control.
- **`tool_error` is a reserved key, set only on the failure path.** Its absence means success, and an implementation must never return it.

## Directory

```
tool_console.py  Tool registry and execution (registration + dispatch)
```

## Progress & goals

One sample tool, `get_weather`, returning fake data; the tool path is wired end-to-end on the messages path (verified live), but the responses side is only statically checked and there are no real tools yet.

Goals:

- Add a permission-confirmation step before execution — a registered tool is callable immediately, so one that reads files or makes network requests is already model-reachable with no gate.
- Add real tools, handling timeouts, pagination, and oversized output.
- Cap how much a tool result may push into `context`.
