# AGENTS.md

把两套形状完全不同的 API 收敛到同一份协议后面。**这是全仓库唯一允许出现 provider 差异的地方**，调用者（[../control_loop.py](../control_loop.py)）只通过协议方法取数据，不 import 这里的任何类。

## 布局

```
protocol.py        三份协议的声明，无实现：llm_protocol / response_protocol / stream_protocol
messages_llm.py    Anthropic Messages API 包装
responses_llm.py   OpenAI Responses API 包装
```

两个 wrapper 文件**结构完全对称**，各有四个东西：

```
<llm 类>        继承 llm_protocol，另有 _params / get_response 两个协议外的方法
<_response 类>  继承 response_protocol，抹平响应形状
<_stream 类>    继承 stream_protocol，只产出文本增量
```

## 约定

- **命名按 API 名，不按厂商名，单复数是有意义的。** `messages_*` / `responses_*` 里的词是 API 名（对应 SDK 的 `client.messages` / `client.responses`），不是厂商名——配置里的 `base_url` 可以指向任何兼容端点（README 的例子厂商叫 deepseek，走的却是 Anthropic 兼容端点），按厂商命名第一天就错。复数 `responses_` 专指 OpenAI 那个 API，单数 `response_` 留给通用的"响应对象"（`response_protocol`、`response.output_text`），别写混。
- **两个 wrapper 必须同步改。** 加功能时两边都要加，否则协议成员缺失会在实例化时 `TypeError`。
- **`@abstractmethod` 是刻意加的，别删。** 裸 `Protocol` 的 `__abstractmethods__` 为空，什么都不强制，清单就退化成注释；加上它、再让两个 wrapper 显式继承，漏实现才会在构造期炸。
- **三份协议各守一层接缝，别互相越界。** `llm_protocol` 管的是"两个 provider 必须都实现"的那一层：`start_stream` / `stream_complete`（循环层唯一会调的）加 `tool_definitions`（`_params` 内部调，循环层不碰）。**`get_response` 与 `get_model_list` 故意不在里面**——理由见下面 OpenAI 侧那条。往 `llm_protocol` 里加成员就等于要求两个 provider 都实现，加之前先问 Anthropic 那侧有没有。
- **协议成员 `raw` 必须是 class 级 `@property`**，不能在 `__init__` 里 `self.raw = raw`。`ABCMeta` 从 class `__dict__` 计算 `__abstractmethods__`，实例属性覆盖不掉抽象属性，照样 `TypeError`。既有的四个类都是 `@property`，照抄。
- **token 属性两侧口径不同，改之前先读 docstring。** Anthropic 的 `input_tokens` **不含**缓存读写、OpenAI 的**已含** `cached_tokens`；`used_context` 与 `cache_hit_rate` 的分母算法因此相反。`total_tokens` 沿用 input+output 口径，量的是"未缓存输入 + 输出"，**不是上下文长度**——要那个用 `used_context`（控制台状态行用的就是它）。两个名字容易看混，**"上下文用量"这个词只能指 `used_context`**。
- **`tool_continuation(results)` 是工具轮的唯一出口**，信封的有无由它决定，调用方只管 `context.extend(response.tool_continuation(results))`。Anthropic 要包成 `assistant`（**必须带完整原始块列表，含 thinking**）+ `user` 两条消息；OpenAI 是裸 item 列表，**不能套 `{"role": ...}` 信封**。调用项由实现从 `self.tool_calls` 现取，与 results 按 `zip` 配对，所以调用方只负责 results 的顺序和条数（照 `response.tool_calls` 遍历生成就不会错）。**不要退回去让调用方传 calls**：那等于允许传一份对不上的列表，`zip` 会静默截断成短的那个，最终表现为服务端拒绝一个看不出原因的请求。
- **`_params()` 是两条路的唯一请求体来源**（[messages_llm.py:18](messages_llm.py#L18) / [responses_llm.py:19](responses_llm.py#L19)）。两侧 key 名不同（`system`/`messages` vs `instructions`/`input`，`output_config` vs `reasoning`），所以各有一份，不抽成模块级函数。**`tools` 字段由它自己经 `self.tool_definitions()` 转换**，所以调用方（循环层）传中立形状即可，两处都不预先转换。
- **工具定义的形状差异只在 `tool_definitions()` 里，也就是只在这两个方法里。** 中立形状是 `{"name", "description", "parameters"}`；Anthropic 要把 `parameters` 改名成 `input_schema` 且**不能**套 `{"type": "function"}`，OpenAI Responses 要**套**上 `{"type": "function"}` 而键名保持 `parameters`。写错的后果不对称：Anthropic 端点直接拒掉整个请求，OpenAI 只是模型看不到工具（静默）。
- **`start_stream` 里 `manager.__enter__()` 那一行才真正发出请求**，`__init__` 不发。返回后连接已经开着，所以调用方必须立刻进 `try`，中间不要插入可能抛异常的代码。
- **`stream_complete` 是 `try: drain finally: close`，顺序不能反。** `close()` 之后再调 `get_final_message()` / `get_final_response()` 会 `RuntimeError: stream closed`，而 drain 自己失败（零事件流、中途网络错误）也必须保证关闭。`close()` 幂等，重复调用安全。
- **`_stream.__iter__` 必须遍历 SDK 流对象本身（`self._raw`），绝不能穿透到内部的 `_raw_stream`。** 终稿快照是 `MessageStream.__stream__` / `ResponseStream.__stream__` 在产出事件的同时累积的，绕过去会得到"有增量、没终稿"，然后在 `stream_complete` 里炸出看不出原因的 `AssertionError`（anthropic）或 `RuntimeError: Didn't receive a response.completed event`（openai）。这条最容易被后来者当成"优化"改坏。
- **流是单次遍历，不可重放。** 底层 SDK 流只有一个共享生成器，遍历到底后再遍历返回空。要完整文本从 `stream_complete` 返回的 `response.output_text` 取。

### Anthropic 侧

- **非流式有一条 21333 的天花板。** SDK 的 `Messages.create` 在发请求前估算耗时 `3600 * max_tokens / 128_000`，超过 600 秒（模型不在 SDK 已知表里时即 `max_tokens > 21333`）直接抛 `ValueError("Streaming is required ...")`。当前配置的 `max_output_tokens` 是 384000，所以 [get_response](messages_llm.py#L44) 对这些模型**必然抛异常**，循环层因此一律走流式。要让它真能用，得传显式 `timeout=`（守卫条件是 `not is_given(timeout)`，给了就跳过），代价是硬吃 10 分钟上限。**OpenAI 侧没有这个守卫。**
- **`MessageStream.text_stream` 是实例属性不是 class 属性**（SDK 在 `__init__` 里挂的），`dir(MessageStream)` 查不到，别因此以为它不存在。本仓库的 `__iter__` 没直接用它，是为了和 OpenAI 侧读起来一致。

### OpenAI 侧

- **没有 `text_stream` 等价物**，`__iter__` 只能自己筛事件（`event.type == "response.output_text.delta"` → `event.delta`），Anthropic 侧 SDK 内部就是同样的筛法。
- **`get_model_list()` 两侧不对称**：OpenAI 侧是活的（[responses_llm.py:9](responses_llm.py#L9)），Anthropic 侧是注释掉的（[messages_llm.py:12-16](messages_llm.py#L12-L16)）。所以它**不在 `llm_protocol` 里**——放进去 `messages_llm(provider)` 就构造期 `TypeError`。`get_response` 同理（当前配置下不可用，见上）。要给模型列表定协议，先决定 Anthropic 侧怎么取。

## 检查

```sh
python -m compileall -q src      # 语法
```

- **不联网的接线检查**：用假的 manager（有 `__exit__`）和 `raw = iter([])` 构造 `_stream` 类。漏实现协议成员会在构造期 `TypeError`；`list(stream) == []` 证明 `__iter__` 可达；`close()` 连调两次验幂等。
- **工具定义转换（不联网）**：拿一条中立定义分别过 `messages_llm.tool_definitions` / `responses_llm.tool_definitions`，断言 Anthropic 侧有 `input_schema`、**没有** `type` 和 `parameters`，OpenAI 侧有 `type == "function"` 且保留 `parameters`；再断言两边都**没有就地改动**传进来的中立 dict。空列表 / `None` 时 `_params()` 必须连 `tools` 键一起省略。
- **真请求验形状**：断言每个增量都是 `str`，且 `"".join(增量) == response.output_text`。这一条同时证明事件筛选和终稿累积都没坏。
- **工具路径**（注册表里已经有一个 `get_weather`，可以直接端到端跑，不必再内联定义绕过循环）：跑到 `tool_use`，再把这次**流式终稿**的 `tool_continuation(results)` 喂给第二次 `start_stream`。**这是价值最高的一条**——assistant 消息原来是服务端拼好的 JSON，现在是客户端从事件累积的，thinking 签名在这一步丢掉的话，就是第二个请求失败。
  - **messages 侧已实测通过**（2026-09-29，deepseek 端点）：工具定义被接受、`stop_reason=tool_use`、第二次请求成功且回答用上了工具结果。**responses 侧仍未跑过。**
  - 纯 `tool_use` 轮**一个文本增量都没有**（实测 `stop=tool_use` 时增量数为 0），这是 [../control_loop.py](../control_loop.py#L57-L61) 那个懒启动 Live 存在的原因——跑这段别指望看到增量，要去断言 `tool_calls`。
- **每次改完问自己**：改动只落在 messages 一侧了吗？responses 侧只有静态检查，端到端没跑过。
