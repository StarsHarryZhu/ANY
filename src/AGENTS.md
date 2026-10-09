# AGENTS.md

## Role

`src/` holds the library source — the entry point [main.py](../main.py) sits at the repo root. Three layers: **loop layer** (the two `.py` files here) → **wrapper layer** ([llm/](llm/)) → **protocol layer** ([llm/protocol.py](llm/protocol.py)); the **tool layer** ([tools/](tools/)) sits alongside and is driven by the loop. Calls only ever go one way: the loop layer knows only the protocol, importing no SDK and no concrete wrapper class.

## Constraints & protocols

- **`control_loop.py` carries no provider branch.** The loop knows only the protocol; every shape difference is the wrapper's job.
- **A Live is torn down before the next turn opens one.** Don't `console.input()` or `print` while a Live is running.
- **A Ctrl-C that lands while the stream is being iterated never reaches `stream_complete`.** The interrupted response is dropped whole; the user half stays in `context` unanswered, which both providers tolerate. Don't add a drain.
- **Keep the two `finally` blocks nested.**
- **The status line uses `used_context` in both of its slots** — never `total_tokens`.
- **`console` is the module-level singleton from [utils.py](utils.py); use it, don't build another.** It must keep `highlight=False`.
- **The protocol in [llm/protocol.py](llm/protocol.py) holds the members both wrappers must implement** — `get_response` / `get_model_list` are the deliberate exclusions (see [llm/AGENTS.md](llm/AGENTS.md)). The two sides account for tokens differently, so read the docstrings before touching any token property.
- **`api_keys.json` lives here and is never committed, pasted, or used as an example.** Its shape is synced with the README schema and [main.py](../main.py).
- **No package has an `__init__.py`.** `src/`, `src/llm/` and `src/tools/` are PEP 420 namespace packages: keep new subpackages that way, and never rely on a package `__init__` for initialization.

## Directory

```
control_loop.py  The REPL loop: model/effort selection, streaming render, tool turn, usage line
utils.py         Config loading, the shared console, and interactive selectors
api_keys.json    Config (schema in ../README.md)
llm/             Protocol + the two provider wrappers (see llm/AGENTS.md)
tools/           Tool registry and execution (see tools/AGENTS.md)
```

## Progress & goals

The loop runs end-to-end on the messages path — selection, streaming render, tool turn, and the usage line all work — and stays provider-agnostic by construction. The responses path shares the loop but has not been run live.

Goals:

- Keep the loop provider-agnostic as tools and providers are added — pressure to branch on the provider here means a wrapper method is missing.
- Confirm the streaming render on the responses path once that path is run live.
