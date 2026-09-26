# AGENTS.md

把两套形状完全不同的 API 收敛到同一份协议后面。**这是全仓库唯一允许出现 provider 差异的地方**，调用者（[../control_loop.py](../control_loop.py)）只通过协议方法取数据，不 import 这里的任何类。

## 布局

```
response_base.py   两份协议的声明，无实现：response_protocol / stream_protocol
anthropic_llm.py   Anthropic Messages API 包装
response_llm.py    OpenAI Responses API 包装
```

两个 wrapper 文件**结构完全对称**，各有四个东西：

```
<llm 类>        _params / get_response / start_stream / stream_complete
<_response 类>  继承 response_protocol，抹平响应形状
<_stream 类>    继承 stream_protocol，只产出文本增量
```

## 约定

- **两个 wrapper 必须同步改。** 加功能时两边都要加，否则协议成员缺失会在实例化时 `TypeError`。
- **`@abstractmethod` 是刻意加的，别删。** 裸 `Protocol` 的 `__abstractmethods__` 为空，什么都不强制，清单就退化成注释；加上它、再让两个 wrapper 显式继承，漏实现才会在构造期炸。
- **协议成员 `raw` 必须是 class 级 `@property`**，不能在 `__init__` 里 `self.raw = raw`。`ABCMeta` 从 class `__dict__` 计算 `__abstractmethods__`，实例属性覆盖不掉抽象属性，照样 `TypeError`。既有的四个类都是 `@property`，照抄。
- **token 属性两侧口径不同，改之前先读 docstring。** Anthropic 的 `input_tokens` **不含**缓存读写、OpenAI 的**已含** `cached_tokens`；`used_context` 与 `cache_hit_rate` 的分母算法因此相反。`total_tokens` 是为了控制台显示沿用 input+output 口径，量的是"未缓存输入 + 输出"，**不是上下文长度**——要那个用 `used_context`。
- **`tool_continuation()` 是工具轮的唯一出口**，信封的有无由它决定，调用方只管 `context.extend(response.tool_continuation(calls, results))`。Anthropic 要包成 `assistant`（**必须带完整原始块列表，含 thinking**）+ `user` 两条消息；OpenAI 是裸 item 列表，**不能套 `{"role": ...}` 信封**。内部按 `zip(calls, results)` 配对，调用方必须保持顺序。
- **`_params()` 是两条路的唯一请求体来源**（[anthropic_llm.py:18](anthropic_llm.py#L18) / [response_llm.py:19](response_llm.py#L19)）。两侧 key 名不同（`system`/`messages` vs `instructions`/`input`，`output_config` vs `reasoning`），所以各有一份，不抽成模块级函数。
- **`start_stream` 里 `manager.__enter__()` 那一行才真正发出请求**，`__init__` 不发。返回后连接已经开着，所以调用方必须立刻进 `try`，中间不要插入可能抛异常的代码。
- **`stream_complete` 是 `try: drain finally: close`，顺序不能反。** `close()` 之后再调 `get_final_message()` / `get_final_response()` 会 `RuntimeError: stream closed`，而 drain 自己失败（零事件流、中途网络错误）也必须保证关闭。`close()` 幂等，重复调用安全。
- **`_stream.__iter__` 必须遍历 SDK 流对象本身（`self._raw`），绝不能穿透到内部的 `_raw_stream`。** 终稿快照是 `MessageStream.__stream__` / `ResponseStream.__stream__` 在产出事件的同时累积的，绕过去会得到"有增量、没终稿"，然后在 `stream_complete` 里炸出看不出原因的 `AssertionError`（anthropic）或 `RuntimeError: Didn't receive a response.completed event`（openai）。这条最容易被后来者当成"优化"改坏。
- **流是单次遍历，不可重放。** 底层 SDK 流只有一个共享生成器，遍历到底后再遍历返回空。要完整文本从 `stream_complete` 返回的 `response.output_text` 取。

### Anthropic 侧

- **非流式有一条 21333 的天花板。** SDK 的 `Messages.create` 在发请求前估算耗时 `3600 * max_tokens / 128_000`，超过 600 秒（模型不在 SDK 已知表里时即 `max_tokens > 21333`）直接抛 `ValueError("Streaming is required ...")`。当前配置的 `max_output_tokens` 是 384000，所以 [get_response](anthropic_llm.py#L32) 对这些模型**必然抛异常**，循环层因此一律走流式。要让它真能用，得传显式 `timeout=`（守卫条件是 `not is_given(timeout)`，给了就跳过），代价是硬吃 10 分钟上限。**OpenAI 侧没有这个守卫。**
- **`MessageStream.text_stream` 是实例属性不是 class 属性**（SDK 在 `__init__` 里挂的），`dir(MessageStream)` 查不到，别因此以为它不存在。本仓库的 `__iter__` 没直接用它，是为了和 OpenAI 侧读起来一致。

### OpenAI 侧

- **没有 `text_stream` 等价物**，`__iter__` 只能自己筛事件（`event.type == "response.output_text.delta"` → `event.delta`），Anthropic 侧 SDK 内部就是同样的筛法。
- **`get_model_list()` 两侧不对称**：OpenAI 侧是活的（[response_llm.py:9](response_llm.py#L9)），Anthropic 侧是注释掉的（[anthropic_llm.py:12-16](anthropic_llm.py#L12-L16)）。**要抽 `llm_protocol` 就别把 `get_model_list` 放进去**，否则 `anthropic_llm(provider)` 会在构造期 `TypeError`。

## 检查

```sh
python -m compileall -q src      # 语法
```

- **不联网的接线检查**：用假的 manager（有 `__exit__`）和 `raw = iter([])` 构造 `_stream` 类。漏实现协议成员会在构造期 `TypeError`；`list(stream) == []` 证明 `__iter__` 可达；`close()` 连调两次验幂等。
- **真请求验形状**：断言每个增量都是 `str`，且 `"".join(增量) == response.output_text`。这一条同时证明事件筛选和终稿累积都没坏。
- **工具路径**（[../tools/AGENTS.md](../tools/AGENTS.md) 的工具表是空的，把内联工具定义直接传给 wrapper 绕过循环）：跑到 `tool_use`，再把这次**流式终稿**的 `tool_continuation` 喂给第二次 `start_stream`。**这是价值最高的一条**——assistant 消息原来是服务端拼好的 JSON，现在是客户端从事件累积的，thinking 签名在这一步丢掉的话，就是第二个请求失败。
- **每次改完问自己**：改动只落在 Anthropic 一侧了吗？OpenAI 侧只有静态检查，端到端没跑过。
