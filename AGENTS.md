# AGENTS.md

## Role

ANY is a multi-turn LLM chat REPL that runs in the terminal. It converges the Anthropic Messages API and the OpenAI Responses API behind one protocol seam — three `Protocol` classes in [src/llm/protocol.py](src/llm/protocol.py): **the loop layer knows only the protocol, never the provider.** This folder is the repo root — entry point, dependency pins, and the conventions that span every subfolder.

Read [src/AGENTS.md](src/AGENTS.md) before changing code, and [src/llm/AGENTS.md](src/llm/AGENTS.md) before touching a wrapper.

## Constraints & protocols

- **Provider shape differences may only live in the wrappers.** An `if provider == ...` in the loop layer means a method belongs on the wrapper, not a fork at the call site; the one sanctioned exception is the entry point's wrapper selection ([main.py](main.py)).
- **The tool-turn continuation envelope is the wrapper's decision; the caller never assembles it** — that block of `context` may only come from `tool_continuation()`. (The loop does build the plain user/assistant messages itself.)
- **Blocking and streaming share one request body.** Each wrapper builds it in its own `_params()`, and both `get_response` and `start_stream` must go through it.
- **Name by API, not by vendor, and singular vs. plural is meaningful.** `messages_*` / `responses_*` name the APIs (the SDK's `client.messages` / `client.responses`), not the vendors — a compatible endpoint can serve either. The plural `responses_` is only the OpenAI API; the singular `response_` is the generic response object. A third provider follows the same axis.
- **The protocol is the single seam across layers.** It is declared in [src/llm/protocol.py](src/llm/protocol.py) and both wrappers explicitly inherit it; the loop layer imports nothing from [src/llm/](src/llm/) — it receives the wrapper by parameter and touches it only through the protocol.
- **`main.py`'s dispatch is three branches — keep the `else`.** It turns a mistyped `API` field into a readable config error instead of a `NameError` on the next line ([main.py:13-20](main.py#L13-L20)). Adding a provider means extending the accepted-value list there too.
- **Run from the repo root.** Every config path is hard-coded relative to the CWD ([utils.py:8](src/utils.py#L8)); a miss is swallowed into `{}` and surfaces later as a `KeyError`.
- **The three pluggable slots are declared in [links.json](links.json) at the repo root; the built-in implementations in `src/` are hardcoded defaults.** A missing, unparsable, or misdirected `links.json` must never crash startup — each slot falls back independently, with one dim line via the shared console. The asymmetry is deliberate: the *default* modules' own import or attribute errors still propagate, because those are repo bugs, not config problems.
- **Provider identity reaches the loop only as an opaque `provider_meta` dict.** The loop never compares it; the `API`-kind compatibility check that decides whether a session may be resumed lives in the session loader ([default_saver_loader.py](src/default_saver_loader.py)).
- **Sessions are named, and the session name is an opaque handle to the loop.** `choose_session` (the naming picker) lives in the saver_loader slot, not the loop; the loop only forwards the name back to `save_session`. Writes are atomic — a `.tmp` file then `os.replace` — and never happen on the cancel path, or at all when the caller passed `context` explicitly. `sessions/` is gitignored plaintext user data, and the `context` it round-trips holds raw SDK blocks — serialized through `model_dump(mode="json")`, which is what preserves Anthropic thinking signatures.
- **Read the version notes before upgrading an SDK, and sync the docs after.** The behavior recorded in the code comments was measured against the pinned versions. Most fragile: the SDK stream object's internals (the wrappers' `__iter__`) and rich Live's overflow policy (see `STREAM_TAIL` in [control_loop.py](src/control_loop.py)).
- **Every AGENTS.md uses one fixed format** — the four top-level sections Role / Constraints & protocols / Directory / Progress & goals (subsections allowed beneath them) — and is written in English. README and code comments are written in Chinese.
- **There is no test framework and no test files.** Verify by hand.

## Directory

```
main.py                  Entry point: loads config and dispatches to the selected wrapper
links.json               Pluggable-slot pointers (choosing module / saver_loader module / system prompt file)
requirements.txt         Four pinned dependencies
.gitignore               Ignore list (api_keys.json, sessions/, .env, .venv, __pycache__, *.log, *.db)
README.md                User-facing docs: install, config schema, running, known limitations
src/                     All source code (see src/AGENTS.md)
  llm/                     Protocol + the two provider wrappers (see src/llm/AGENTS.md)
  tools/                   Tool registry and execution (see src/tools/AGENTS.md)
sessions/                One JSON file per named session; gitignored user data
_reference_api_respond/  Reference data: two hand-saved raw response samples, not referenced by code
.venv/                   Python 3.14 virtual environment
```

## Progress & goals

Both providers sit behind the same protocol. The messages path is wired through the loop and verified end-to-end, the tool turn included, against a third-party Anthropic-compatible endpoint; the responses path is written but only checked statically and at construction.

The three pluggable slots, the session file, and the external system-prompt file are in place. Slot resolution, the fallbacks, and the session round trip are checked by hand; the one thing still unverified live is resuming a saved session that ends in a tool turn (the replayed blocks must be accepted by the endpoint).

Goals, roughly in order:

- Resume a session ending in a tool turn against a live endpoint — the replay of stored blocks is the untested half of session persistence.
- Real tools plus a permission-confirmation step before execution (see [src/tools/AGENTS.md](src/tools/AGENTS.md)).
- Run the responses path end-to-end against a live OpenAI-compatible endpoint.
- Settle `get_response`: make it usable under the configured output limit, or drop it.
