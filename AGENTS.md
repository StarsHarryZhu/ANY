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
- **Run from the repo root.** The config path is hard-coded relative to the CWD ([utils.py:7](src/utils.py#L7)); a miss is swallowed into `{}` and surfaces later as a `KeyError`.
- **Read the version notes before upgrading an SDK, and sync the docs after.** The behavior recorded in the code comments was measured against the pinned versions. Most fragile: the SDK stream object's internals (the wrappers' `__iter__`) and rich Live's overflow policy (see `STREAM_TAIL` in [control_loop.py](src/control_loop.py)).
- **Every AGENTS.md uses one fixed format** — the four top-level sections Role / Constraints & protocols / Directory / Progress & goals (subsections allowed beneath them) — and is written in English. README and code comments are written in Chinese.
- **There is no test framework and no test files.** Verify by hand.

## Directory

```
main.py                  Entry point: loads config and dispatches to the selected wrapper
requirements.txt         Four pinned dependencies
.gitignore               Ignore list (api_keys.json, .env, .venv, __pycache__, *.log, *.db)
README.md                User-facing docs: install, config schema, running, known limitations
src/                     All source code (see src/AGENTS.md)
  llm/                     Protocol + the two provider wrappers (see src/llm/AGENTS.md)
  tools/                   Tool registry and execution (see src/tools/AGENTS.md)
_reference_api_respond/  Reference data: two hand-saved raw response samples, not referenced by code
.venv/                   Python 3.14 virtual environment
```

## Progress & goals

Both providers sit behind the same protocol. The messages path is wired through the loop and verified end-to-end, the tool turn included, against a third-party Anthropic-compatible endpoint; the responses path is written but only checked statically and at construction.

Goals, roughly in order:

- Real tools plus a permission-confirmation step before execution (see [src/tools/AGENTS.md](src/tools/AGENTS.md)).
- Run the responses path end-to-end against a live OpenAI-compatible endpoint.
- Settle `get_response`: make it usable under the configured output limit, or drop it.
