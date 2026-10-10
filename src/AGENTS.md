# AGENTS.md

## Role

`src/` holds the library source — the entry point [main.py](../main.py) sits at the repo root. Three layers: **loop layer** ([control_loop.py](control_loop.py) plus the built-in implementations of the three pluggable slots, [default_choosing.py](default_choosing.py) and [default_saver_loader.py](default_saver_loader.py), with the external prompt file [default_system_prompt.md](default_system_prompt.md)) → **wrapper layer** ([llm/](llm/)) → **protocol layer** ([llm/protocol.py](llm/protocol.py)); the **tool layer** ([tools/](tools/)) sits alongside and is driven by the loop. Calls only ever go one way: the loop layer knows only the protocol, importing no SDK and no concrete wrapper class.

## Constraints & protocols

- **`control_loop.py` carries no provider branch.** The loop knows only the protocol; every shape difference is the wrapper's job. `provider_meta` is forwarded to the session loader as an opaque dict — the `API`-kind comparison lives there, not in the loop.
- **The pickers' home is [default_choosing.py](default_choosing.py).** Don't reintroduce selection code into `control_loop.py`; the loop only calls `model_choose` / `reasoning_choose` through the slot and treats `None` as cancellation.
- **The three slots are resolved once at the top of `control_loop`, through [utils.py](utils.py)'s `load_links` / `resolve_module` / `load_system_prompt`,** and each one degrades to its hardcoded default with one dim line — a broken `links.json` is never fatal (the defaults' own errors still propagate). The pointer file lives at the repo root, not here.
- **Sessions are named, and the name is opaque to the loop.** `choose_session` (the session picker and the name prompt) is a member of the saver_loader slot — the loop only forwards the returned name back into `load_session` / `save_session` and never builds a path or knows the layout. Writes are atomic (a `.tmp` file then `os.replace`) and never happen on the cancel path, nor when the caller passed `context` explicitly. The exit save is deliberate: a turn interrupted mid-stream leaves a legal unanswered user message that is worth keeping. The store (`../sessions/`) is gitignored plaintext; the `context` it holds contains raw SDK blocks and goes through `model_dump(mode="json")` — that is what keeps Anthropic thinking signatures replayable.
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
control_loop.py            The REPL loop: streaming render, tool turn, usage line, session save/resume
default_choosing.py        Built-in pickers (the choosing_module slot)
default_saver_loader.py    Built-in named-session store, atomic writes (the saver_loader_module slot)
default_system_prompt.md   Extra system-prompt text appended after the date line (empty by default)
utils.py                   Config/links loading, slot resolution, the shared console, selectors
api_keys.json              Config (schema in ../README.md)
llm/                       Protocol + the two provider wrappers (see llm/AGENTS.md)
tools/                     Tool registry and execution (see tools/AGENTS.md)
```

## Progress & goals

The loop runs end-to-end on the messages path — selection, streaming render, tool turn, the usage line, and session save/resume all work — and stays provider-agnostic by construction. The responses path shares the loop but has not been run live. Slot resolution, every fallback branch, and the save/load round trip were checked by hand.

Goals:

- Keep the loop provider-agnostic as tools and providers are added — pressure to branch on the provider here means a wrapper method is missing.
- Confirm the streaming render on the responses path once that path is run live.
- Resume a session that ends in a tool turn against a live endpoint: replaying the stored blocks is the untested half of persistence.
