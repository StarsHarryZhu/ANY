# AGENTS.md

## Role

Fold two completely differently-shaped APIs behind one protocol. **This is the only folder where provider shape differences are handled** — the entry point's wrapper selection ([../../main.py](../../main.py)) is the one exception. The caller ([../control_loop.py](../control_loop.py)) reads data only through protocol methods and imports none of the classes here.

## Constraints & protocols

The three protocols are declared in [protocol.py](protocol.py): `llm_protocol` (the members both wrappers must implement), `response_protocol` (a response object), and `stream_protocol` (a stream object). Across the three classes each wrapper defines, every protocol has an explicit implementer, so a missing member fails at construction.

- **Name by API, not by vendor, and singular vs. plural is meaningful.** `messages_*` / `responses_*` name the APIs; the plural `responses_` is only the OpenAI API, the singular `response_` is the generic response object.
- **Change the two wrappers in sync.** Their method surface is symmetric, so a member added to one belongs on the other — the one exception is `get_model_list`, which is not a protocol member and is called out below. The bodies are not symmetric, though: the `_params` key names differ, and OpenAI alone sets `temperature` and `tool_choice` (only `tool_choice`'s value shape differs between the APIs). "Sync" means matching the protocol members, not copy-pasting a body.
- **Keep the `@abstractmethod`s and the class-level `@property`s.** They are what make a missing member fail at construction instead of at runtime.
- **Build the request body in `_params()` only.** `get_response` and `start_stream` both go through it.
- **Convert tool shapes in `tool_definitions()` only.** The registry hands over the neutral `{name, description, parameters}`; each side reshapes it here.
- **`tool_continuation(results)` is the only way a tool turn re-enters `context`.** The envelope is this side's decision, and the call items come from `self.tool_calls`, not from the caller.
- **`start_stream` sends the request on `manager.__enter__()`.** The caller must put nothing that can raise between that call and its `try`.
- **`stream_complete` is `try: drain finally: close`, and `__iter__` consumes the SDK stream object itself, never its inner `_raw_stream`.** The stream is single-pass.
- **Token properties differ per provider.** `input_tokens` excludes cache on Anthropic and includes it on OpenAI, so `used_context` and `cache_hit_rate` invert accordingly. Read the docstrings.
- **`get_response` and `get_model_list` stay out of `llm_protocol`, for different reasons.** `get_model_list` is asymmetric — OpenAI implements it, Anthropic has it commented out. `get_response` is unusable on the Anthropic side under the configured output limit (the SDK's non-streaming guard raises; OpenAI has no such guard — see the code comment).

### Per provider

- **Anthropic**: non-streaming has a 21333-token ceiling (`Messages.create` estimates its own run time); the configured output limit sits above it, so a blocking call raises.
- **OpenAI**: the SDK has no `text_stream`, so `__iter__` filters events itself; `get_model_list` is live here but commented out on the Anthropic side.

## Directory

```
protocol.py        The three protocol declarations, no implementation
messages_llm.py    Anthropic Messages API wrapper
responses_llm.py   OpenAI Responses API wrapper
```

## Progress & goals

The messages path is verified end-to-end against a live endpoint, the tool turn included — the thinking signature survives the round trip. The responses side is written but has only been checked statically.

Goals:

- Run the responses side end-to-end, tool turn included.
- Decide `get_response`'s fate under the configured output limit.
- Give the model list a protocol once the Anthropic side has a way to fetch it.
