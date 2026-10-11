# ANY

> A multi-turn LLM chat REPL for the terminal — and a vibe-coding experiment.

[中文](README_zh.md)

ANY converges the Anthropic Messages API and the OpenAI Responses API behind a single
protocol seam: the control loop knows only the protocol, never which vendor it is talking
to. The project was written almost entirely by an LLM in conversation — the point of this
repository is to see how far that gets.

It is not a product. Not on PyPI, no LICENSE, no tests, and the interface can change at
any time.

## What it does

- Streaming multi-turn chat in the terminal: the reply renders as it arrives, then is
  swapped for the finished Markdown.
- Two vendors, two APIs, with no provider branch anywhere in the loop layer.
- Tool calls: the envelope differences between the two (Anthropic wraps
  `assistant`/`user` messages and echoes thinking blocks back; OpenAI uses bare items)
  are absorbed entirely inside the wrapper.
- Named sessions: one file per session; at startup you either resume an old one or create
  a new one. Saved automatically every turn, and resuming replays the history to the
  terminal.
- Three pluggable slots: the model/effort picker, session storage, and the system-prompt
  file are all pointed to by `configs/links.json`. A missing or broken file falls back
  per slot and never takes startup down with it.
- A startup tool preset: `configs/presets/` decides which tools this session may use.

## Status: what's verified, what isn't

| Verified | Not verified |
| --- | --- |
| The `messages` path end-to-end, tool turn included (against a third-party Anthropic-compatible endpoint) | The `responses` path (OpenAI): written, checked statically and at construction only, never run against a live endpoint |
| Slot resolution and the three fallbacks | Resuming a session that **ends in a tool turn**: the replayed blocks have not yet been accepted by a live endpoint |
| The session save / resume round trip | `get_response`, which is unusable under the configured output limit |
| The tool layer: both tools, each one's failure branches, and the preset matrix (walked by hand) | |

## Requirements

Python 3.14 and six pinned dependencies — see [requirements.txt](requirements.txt).

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configure

You need to create `configs/api_keys.json` yourself (it is gitignored). The minimal
working shape:

```json
{
  "current_provider": "deepseek",
  "providers": {
    "deepseek": {
      "API": "messages",
      "base_url": "https://api.deepseek.com/anthropic",
      "api_key": "sk-...",
      "models": [
        {
          "name": "deepseek-flash",
          "context_window": 1000000,
          "max_output_tokens": 384000,
          "efforts": ["none", "low", "high", "max"]
        }
      ]
    }
  }
}
```

- `API` picks the wrapper; it is `"messages"` or `"responses"`. That names the API kind,
  not the vendor — one compatible endpoint may serve either.
- The entries in `efforts` are passed straight through to the endpoint. Anthropic's
  official enum is `low`/`medium`/`high`/`xhigh`/`max`; what any other endpoint accepts
  is yours to find out.
- Every config path is hard-coded relative to the CWD, so the program must be run **from
  the repo root**.

## Run

```bash
python main.py
```

Startup order: pick a session → pick a model → pick a reasoning effort → pick a tool
preset → start chatting. `Ctrl-C` / `Ctrl-D` to exit.

## Layout

```
main.py                  Entry point: loads config, dispatches on the API field to the matching wrapper
configs/                 Every .json config (CWD-relative)
  links.json               Pointers for the three pluggable slots
  tools.json               The tool table: module path -> class name, the only source of tools
  presets/                 Tool presets; presets_dir.json is the startup menu
  api_keys.json            Main config (gitignored, you create it)
src/                     All source code
  control_loop.py          The control loop
  llm/                     The protocol + the two provider wrappers
  tools/                   Tool registry and execution
sessions/                One JSON per session; gitignored plaintext user data
```

## Known limitations

- There is no permission confirmation before a tool runs; once registered, a tool is
  callable. `current_location` sends your exit IP to third-party geolocation services on
  every call, with no caching; three sources fall back in sequence, up to about
  24 seconds worst case.
- IP geolocation is city-level only; `ip-api.com`'s free tier is HTTP-only and not
  licensed for commercial use.
- There are no tests and no test framework — everything is verified by hand.
- Sessions are plaintext and unbounded, rewritten whole every turn; an over-window error
  comes from the endpoint and is never truncated automatically.
- Whether a resumed history is accepted depends on the endpoint — specifically, on
  whether it still honors the thinking signatures it produced itself.

## Docs

[AGENTS.md](AGENTS.md) and the three files under `src/` are the developer-facing source
of truth: the architectural constraints, each folder's responsibilities, and current
progress all live there. This README only says what it is, what it does, and what has not
been verified yet.
