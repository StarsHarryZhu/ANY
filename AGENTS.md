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
- **Run from the repo root.** Every config path is hard-coded relative to the CWD — the .json ones under [configs/](configs/) ([utils.py:9](src/utils.py#L9)); a miss is swallowed into `{}` and surfaces later as a `KeyError`.
- **The three pluggable slots are declared in [configs/links.json](configs/links.json); the built-in implementations in `src/` are hardcoded defaults.** A missing, unparsable, or misdirected `links.json` must never crash startup — each slot falls back independently, with one dim line via the shared console. The asymmetry is deliberate: the *default* modules' own import or attribute errors still propagate, because those are repo bugs, not config problems.
- **The tool table is config too: [configs/tools.json](configs/tools.json) maps module paths to class names and is the only source of tools** — no fallback list in code, so a missing or unreadable file registers no tools at all, and an entry that fails to resolve is skipped — each notice is a single dim line, never a pair. An entry that resolves to a class which does not implement the tool contract raises instead, naming the class. The failure direction is always fewer tools, never more.
- **Every shipped `.json` config carries a top-level `"version"` — that is how this build tells whether it can read the file at all.** Each file has its own format number, and each of the five gates checks it after parsing and before using anything: a missing field, a non-integer, or a number this build does not know is treated exactly like an unreadable file — one dim line naming the file and the reason, then that file's own fallback (the built-in defaults for `links.json` / `presets_dir.json`, no tools for `tools.json`, no commands for `commands.json`, and a skipped preset document, which widens to every tool when nothing usable is left). The gate never raises, because "a config problem never crashes startup" is the rule it has to keep. [configs/api_keys.json](configs/api_keys.json) is deliberately exempt: it is hand-written, gitignored, and has no built-in default to fall back to. The session store's `SESSION_FORMAT` is a different scheme for user data — the two are never compared.
- **The tool preset is config too: [configs/presets/presets_dir.json](configs/presets/presets_dir.json) lists the preset files on offer, and that list is the startup picker's menu.** It degrades like `links.json` — an unusable preset is skipped with one dim line, and the fallback is the built-in [configs/presets/full/preset.json](configs/presets/full/preset.json). An entry that matches no tool is only skipped, never widened back to "all tools": a preset exists to narrow.
- **Provider identity reaches the loop only as an opaque `provider_meta` dict.** The loop never compares it; the `API`-kind compatibility check that decides whether a session may be resumed lives in the session loader ([default_saver_loader.py](src/default_saver_loader.py)).
- **A line starting with `/` is a command, and commands are config too: [configs/commands.json](configs/commands.json) maps `/<name>` to a tool name.** The loop parses and runs it (through the same `tool_run` a model tool call uses, which is why the `[tool]` line matches); a command with trailing text runs first and then sends the rest to the model as an ordinary message. A `/name` that is not in the table is rewritten to `user_command(name) <text>` and handed to the model — every command is a registered tool, so the model can recognize a mistyped one and call the tool itself. The file degrades like the rest: unreadable or missing means no commands, never a crash.
- **Sessions are named, and the session name is an opaque handle to the loop.** `choose_session` (the naming picker) lives in the saver_loader slot, not the loop; the loop only forwards the name back to `save_session`, whose signature is `(name, context, messages, model, effort, provider_meta)`. Writes are atomic — a `.tmp` file then `os.replace` — and never happen on the cancel path, or at all when the caller passed `context` explicitly. `sessions/` is gitignored plaintext user data, and the two lists it round-trips hold raw SDK blocks — serialized through `model_dump(mode="json")`, which is what preserves Anthropic thinking signatures. Resuming replays the history to the terminal, but through the wrapper: the loop renders the neutral rows `context_display()` returns and never reads a provider block itself.
- **Two histories, and only a compaction pulls them apart.** `context` is the working set — the only thing ever sent to the model — and `messages` is the full conversation, append-only; `save_session` writes both. `compact` replaces `context` with a summary and leaves `messages` alone; the resume replay shows the last 50 of `messages`. The store is at format version 2, and a version-1 file is set aside as `.bak` rather than upgraded.
- **Read the version notes before upgrading an SDK, and sync the docs after.** The behavior recorded in the code comments was measured against the pinned versions. Most fragile: the SDK stream object's internals (the wrappers' `__iter__`) and rich Live's overflow policy (see `STREAM_TAIL` in [control_loop.py](src/control_loop.py)).
- **Every AGENTS.md uses one fixed format** — the four top-level sections Role / Constraints & protocols / Directory / Progress & goals (subsections allowed beneath them) — and is written in English. The README is bilingual, kept in sync: [README.md](README.md) in English, [README_zh.md](README_zh.md) in Chinese. Code comments are written in Chinese.
- **There is no test framework and no test files.** Verify by hand.

## Directory

```
main.py                  Entry point: loads config and dispatches to the selected wrapper
configs/                 Every .json config, CWD-relative like the rest (see src/AGENTS.md)
                         The five shipped here all carry "version": 1; api_keys.json is the exception.
  links.json               Pluggable-slot pointers (choosing module / saver_loader module / system prompt file)
  tools.json               The tool table: module path -> class name (the only source of tools)
  commands.json            Slash commands: /<name> -> tool name (the loop's own config, not the tool layer's)
  presets/presets_dir.json The tool presets on offer — the startup picker's menu
  presets/full/preset.json The shipped preset ("全量模式"): no restriction, every tool
  api_keys.json            Main config for this machine (gitignored, no version field; schema in README.md)
requirements.txt         Six pinned dependencies
.gitignore               Ignore list (api_keys.json, sessions/, .env, .venv, __pycache__, *.log, *.db)
README.md                User-facing docs, English: install, config schema, running, known limitations
README_zh.md             The same README in Chinese; the two are kept in sync
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

The tool layer ships three real tools behind the startup preset — `current_time`, `current_location` and `compact` (see [src/tools/AGENTS.md](src/tools/AGENTS.md)); the preset matrix, all three tools' failure branches and the registry's error paths are checked by hand through the tool layer.

Slash commands and `compact` are the newest layer: `commands.json`, the `user_command(...)` fallback, the `context`/`messages` split and the 50-row replay were checked by hand with a scripted fake wrapper, never against a live endpoint — the summarize turn especially, which is the first place the loop calls the model from inside a tool call.

Goals, roughly in order:

- Run `/compact` against a live endpoint, then continue the conversation from the summary — a nested model call inside a tool call has never been on the wire.
- Resume a session ending in a tool turn against a live endpoint — the replay of stored blocks is the untested half of session persistence.
- A permission-confirmation step before tool execution (see [src/tools/AGENTS.md](src/tools/AGENTS.md)) — the tools load, but they are callable the moment they are registered.
- Run the responses path end-to-end against a live OpenAI-compatible endpoint.
- Settle `get_response`: make it usable under the configured output limit, or drop it.
