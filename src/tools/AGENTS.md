# AGENTS.md

## Role

Tool definition registration and execution, plus the startup preset that decides which tools are live. One backend today, the console registry, driven by [../control_loop.py](../control_loop.py): construct → `tool_define()` into `start_stream` → `tool_run()` per call.

## Constraints & protocols

- **The registry stores the neutral shape, never a provider's wire shape** — `{name, description, parameters}`. Turning it into wire shapes is the wrapper layer's job ([../llm/](../llm/)); don't pre-convert here.
- **A tool is a class in its own module** ([timer.py](timer.py), [location.py](location.py), [compact.py](compact.py)) with four members: `ID` (a positive int, written in hex), `DESCRIPTION`, `toolcall()`, and `get_method()` returning `{"name", "id", "description", "parameters"}`. `name` is `type(self).__name__`, so the class name *is* the tool name, and `parameters` is a JSON Schema (`current_time` and `current_location` take none, `compact` too). Registering a tool is one line in [tools.json](../../configs/tools.json) — never add a second source of truth beside `get_method()`.
- **`NEEDS_CONTEXT = True` is the optional fifth member: it is how a tool declares that it needs the session, not just its JSON arguments.** Absent (the normal case) means `toolcall(**params)` and nothing else; declared, `tool_run` passes two extra keyword arguments — `context` (the loop's live working list, by reference) and `complete` (a callable the loop built: `complete(instructions, input) -> str`, one plain model turn). `_build_registry` validates the flag is a `bool` and records it, and `tool_run` consults the registry rather than trying the call, because passing them to a tool that does not take them is a `TypeError`. Two consequences to hold on to: `context` and `complete` are **reserved argument names** (a tool's JSON Schema must not use them), and **a `context`-aware tool rewrites the list in place** (`context[:] = [...]`, never `context = [...]`) or the loop's own reference never sees the change. The tool layer still imports no wrapper and knows no provider: the model call is the loop's callback, handed over.
- **IDs are hand-assigned and unique; `0` and the name `no-restriction` are reserved for the preset sentinel.** [`_build_registry`](_tool_console.py) validates the four `get_method()` keys, the `parameters` shape, the ID, and both name- and ID-uniqueness at startup, and **raises** — those are repo bugs, not config problems. Name-uniqueness is not optional: `impls` is keyed by name and would silently shadow.
- **Tool constructors must be side-effect free.** Every class listed in [tools.json](../../configs/tools.json) is imported, constructed and validated before the preset discards some of them.
- **The tool table is config.** [tools.json](../../configs/tools.json) maps module paths to class names and is the only source of tools; `_load_tool_classes` is the only place that imports a tool module, so a tool's own import-time dependency failures all land there. A bad entry (unimportable module, missing name, a non-class) is skipped with one dim line, which can only ever remove tools; a missing or unreadable file registers no tools at all — each of those notices is one dim line, never a pair. An entry that resolves to a class which does not implement the contract (no `get_method()` or `toolcall()`) reaches `_build_registry` and raises. There is deliberately no built-in fallback list — a hardcoded default would be a second registry.
- **A preset filters; it does not reorder.** `_select_tools` returns the selected tools in registry order, so the model-facing order is always `tools.json`'s order, whatever order the preset lists them in.
- **The tool layer owns the preset.** [presets_dir.json](../../configs/presets/presets_dir.json) lists the usable preset files, and that list *is* the startup picker's menu; each preset file is `{"version", "preset_name", "tools"}`, where `tools` is a list of `(name, id)` pairs. Read the list through `utils.load_preset_files()`, not by opening root files here.
- **Preset documents are version-gated too, and the gate lives here** — `_load_presets` is the only place a preset file is opened, so it covers both routes in (the ones `presets_dir.json` lists and the `DEFAULT_PRESET_FILES` fallback). `PRESET_FORMAT` is that file's own format number; the check runs after `isinstance(document, dict)`, before the `tools` check, and its reason is **folded into the existing collapsed `preset(s) skipped:` line** — never a second notice, and never a call to the printing helpers, or one bad file would speak twice. A version mismatch skips the preset exactly as an unreadable one does, including the outcome when nothing usable is left (the built-in all-tools fallback): that widening is pre-existing and deliberate, not a new hole.
- **Every preset failure degrades with one dim line and never crashes startup** — the same rule as `links.json`. Unreadable list → the built-in `configs/presets/full/preset.json`; an unusable preset is skipped; nothing usable, or the picker cancelled → all tools; an empty or unmatched list → no tools, and it says so, because an empty `tools` is silently dropped by the wrappers' `if tools:`. **An entry that matches no tool is only skipped** — a preset exists to narrow, so a typo must never widen the set back to everything.
- **The preset picker is the one picker outside [../default_choosing.py](../default_choosing.py).** That rule is scoped to the loop layer, and the loop does not know about tools; moving it into the `choosing_module` slot would mean adding a member to the slot's contract, which makes every existing custom chooser fall back to the default.
- **`impls` keys must match the `name`s in `tools`.** A mismatch raises only inside `tool_run` — though both are built from the same registry entries here, so they cannot drift.
- **`tool_run` takes `arguments` as a JSON string**, already unified by the wrapper's `tool_call_arguments()`. Its `context` / `complete` parameters are the `NEEDS_CONTEXT` channel; the slash-command path in the loop calls the same `tool_run` the model's tool turns do, so a command and a tool call are one code path with two callers. The display differs for a `NEEDS_CONTEXT` tool on the command path — the loop prints the new context usage instead of the returned JSON (see [../AGENTS.md](../AGENTS.md)) — which is a decision about the loop's own UI, not about this layer's contract.
- **`tool_run` never fails the caller for a missing tool.** A command whose `commands.json` entry names a tool that is not registered (typo, or filtered out by the preset) comes back as the ordinary `tool_error` text and is printed as-is; the layer's failure direction stays "fewer tools", never a crash.
- **The return value is `json.dumps`'d** (with `ensure_ascii=False`): return a JSON-serializable value and let `tool_run` serialize it — don't pre-serialize.
- **`tool_run` converts ordinary tool errors (`Exception`) into error text for the model and never re-raises them** — a bad name, bad JSON, a bad signature, or the tool raising. `BaseException` subclasses (`KeyboardInterrupt`, `SystemExit`) still propagate, so Ctrl-C stays in control.
- **`tool_error` is a reserved key, set only on the failure path.** Its absence means success, and an implementation must never return it — a tool that fails as a whole (every location source down) must `raise` instead, or its own failure becomes indistinguishable from `tool_run`'s.

## Directory

```
_tool_console.py  Tool registry, preset resolution (incl. PRESET_FORMAT) and execution
timer.py          current_time — local time at second resolution, ID 0x01
location.py       current_location — IP geolocation, three-source fallback, ID 0x02
compact.py        compact — summarize the conversation and replace it, ID 0x03, NEEDS_CONTEXT
../../configs/    The .json config: tools.json (the tool table, the only source of tools), presets/
```

## Progress & goals

Three real tools behind the startup preset; the sample `get_weather` is gone and the tool turn is unchanged on the wire. Because the registry is built from the tool classes, `impls` and `tools` can no longer drift apart. The preset matrix, both original tools' failure branches, the registry's error paths, and `compact`'s four branches (empty context, empty summary, the in-place rewrite, an unregistered tool name) were checked by hand through the tool layer; the loop end was not re-run live.

The preset version gate was checked by hand as well: a stamped preset loads, and a missing / `2` / not-an-object / no-`tools`-list document each produce exactly one `preset(s) skipped:` reason, with the not-a-dict and no-list diagnoses unchanged.

Goals:

- Add a permission-confirmation step before execution — a registered tool is callable immediately, and `current_location` already makes an outbound network request with no gate.
- Cap how much a tool result may push into `context` (`compact` bounds itself, but neither of the other two does).
- Decide what a `NEEDS_CONTEXT` tool may do to `context` — today it is the whole list, in place, with nothing stopping a tool from emptying it.
