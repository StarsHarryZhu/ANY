# AGENTS.md

## Role

Tool definition registration and execution, plus the startup preset that decides which tools are live. One backend today, the console registry, driven by [../control_loop.py](../control_loop.py): construct → `tool_define()` into `start_stream` → `tool_run()` per call.

## Constraints & protocols

- **The registry stores the neutral shape, never a provider's wire shape** — `{name, description, parameters}`. Turning it into wire shapes is the wrapper layer's job ([../llm/](../llm/)); don't pre-convert here.
- **A tool is a class in its own module** ([timer.py](timer.py), [location.py](location.py)) with four members: `ID` (a positive int, written in hex), `DESCRIPTION`, `toolcall()`, and `get_method()` returning `{"name", "id", "description", "parameters"}`. `name` is `type(self).__name__`, so the class name *is* the tool name, and `parameters` is a JSON Schema (both tools today take none). Registering a tool is one line in [tools.json](../../configs/tools.json) — never add a second source of truth beside `get_method()`.
- **IDs are hand-assigned and unique; `0` and the name `no-restriction` are reserved for the preset sentinel.** [`_build_registry`](_tool_console.py) validates the four `get_method()` keys, the `parameters` shape, the ID, and both name- and ID-uniqueness at startup, and **raises** — those are repo bugs, not config problems. Name-uniqueness is not optional: `impls` is keyed by name and would silently shadow.
- **Tool constructors must be side-effect free.** Every class listed in [tools.json](../../configs/tools.json) is imported, constructed and validated before the preset discards some of them.
- **The tool table is config.** [tools.json](../../configs/tools.json) maps module paths to class names and is the only source of tools; `_load_tool_classes` is the only place that imports a tool module, so a tool's own import-time dependency failures all land there. A bad entry (unimportable module, missing name, a non-class) is skipped with one dim line, which can only ever remove tools; a missing or unreadable file registers no tools at all — each of those notices is one dim line, never a pair. An entry that resolves to a class which does not implement the contract (no `get_method()` or `toolcall()`) reaches `_build_registry` and raises. There is deliberately no built-in fallback list — a hardcoded default would be a second registry.
- **A preset filters; it does not reorder.** `_select_tools` returns the selected tools in registry order, so the model-facing order is always `tools.json`'s order, whatever order the preset lists them in.
- **The tool layer owns the preset.** [presets_dir.json](../../configs/presets/presets_dir.json) lists the usable preset files, and that list *is* the startup picker's menu; each preset file is `{"preset_name", "tools"}`, where `tools` is a list of `(name, id)` pairs. Read the list through `utils.load_preset_files()`, not by opening root files here.
- **Every preset failure degrades with one dim line and never crashes startup** — the same rule as `links.json`. Unreadable list → the built-in `configs/presets/full/preset.json`; an unusable preset is skipped; nothing usable, or the picker cancelled → all tools; an empty or unmatched list → no tools, and it says so, because an empty `tools` is silently dropped by the wrappers' `if tools:`. **An entry that matches no tool is only skipped** — a preset exists to narrow, so a typo must never widen the set back to everything.
- **The preset picker is the one picker outside [../default_choosing.py](../default_choosing.py).** That rule is scoped to the loop layer, and the loop does not know about tools; moving it into the `choosing_module` slot would mean adding a member to the slot's contract, which makes every existing custom chooser fall back to the default.
- **`impls` keys must match the `name`s in `tools`.** A mismatch raises only inside `tool_run` — though both are built from the same registry entries here, so they cannot drift.
- **`tool_run` takes `arguments` as a JSON string**, already unified by the wrapper's `tool_call_arguments()`.
- **The return value is `json.dumps`'d** (with `ensure_ascii=False`): return a JSON-serializable value and let `tool_run` serialize it — don't pre-serialize.
- **`tool_run` converts ordinary tool errors (`Exception`) into error text for the model and never re-raises them** — a bad name, bad JSON, a bad signature, or the tool raising. `BaseException` subclasses (`KeyboardInterrupt`, `SystemExit`) still propagate, so Ctrl-C stays in control.
- **`tool_error` is a reserved key, set only on the failure path.** Its absence means success, and an implementation must never return it — a tool that fails as a whole (every location source down) must `raise` instead, or its own failure becomes indistinguishable from `tool_run`'s.

## Directory

```
_tool_console.py  Tool registry, preset resolution and execution (registration + dispatch)
timer.py          current_time — local time at second resolution, ID 0x01
location.py       current_location — IP geolocation, three-source fallback, ID 0x02
../../configs/    The .json config: tools.json (the tool table, the only source of tools), presets/
```

## Progress & goals

Two real tools behind the startup preset; the sample `get_weather` is gone and the tool turn is unchanged on the wire. Because the registry is built from the tool classes, `impls` and `tools` can no longer drift apart. The preset matrix, both tools' failure branches, and the registry's error paths were checked by hand through the tool layer; the loop end was not re-run live.

Goals:

- Add a permission-confirmation step before execution — a registered tool is callable immediately, and `current_location` already makes an outbound network request with no gate.
- Cap how much a tool result may push into `context` (neither tool bounds its output today).
