# AGENTS.md

工具的定义注册与执行。目前只有控制台一个后端，被 [../control_loop.py](../control_loop.py) 以固定三步使用：构造 → `tool_define()` 传给 `start_stream`（**线上形状由 wrapper 转，本层只存中立形状**，见下）→ 拿到工具调用后逐个 `tool_run()`。

## 布局

```
tool_console.py   工具注册表与执行：self.tools（定义）/ self.impls（实现）/ tool_define / tool_run
```

## 约定

- **`self.tools` / `self.impls` 里有一个样例工具 `get_weather`**（[tool_console.py:8-27](tool_console.py#L8-L27)），所以 `tool_define()` 返回非空列表，两个 wrapper 都会真的带上 `tools` 参数——**工具调用链路已经接通**，不再是空表。它是照抄用的模板：注册新工具就是往这两个容器里各填一份，真接 API 时换掉 `get_weather` 的实现即可。
- **注册表里存的是中立形状，不是任何一家的线上形状**，这是本文件最容易踩的坑：

  ```python
  {"name": str, "description": str, "parameters": <JSON Schema>}
  ```

  转换在 [../llm/](../llm/) 层，由 `llm.tool_definitions()` 做：Anthropic 把 `parameters` 改名成 `input_schema`，OpenAI Responses 在外面包一层 `{"type": "function"}`（键名仍叫 `parameters`）。**别在这里预先转换**——[control_loop.py:47](../control_loop.py#L47) 传的就是中立列表，wrapper 会再转一次：注册表若存的是 Anthropic 形状（`input_schema`），转换时 `tool["parameters"]` 直接 `KeyError`；若存的是 OpenAI 形状，Anthropic 侧凑巧还能跑（键名正好对得上，多出来的 `type` 被忽略）——**别依赖这个巧合**。
- **`tool_run` 的 `arguments` 是 JSON 字符串，不是 dict。** 协议层已统一过：`tool_call_arguments()` 保证两侧都吐 JSON 字符串（Anthropic 的 `call.input` 本来是 dict，wrapper 会 `dumps` 一次），这里直接 `json.loads` 即可，不要额外判类型。
- **`impls` 的键必须和 `tools` 里的 `name` 完全一致。** 对不上不会在注册时报错，而是在 `tool_run` 里 `KeyError`。
- **返回值会被 `json.dumps(..., ensure_ascii=False)` 序列化**，实现要么返回可 JSON 序列化的值，要么自己返回序列化好的字符串。
- **`tool_run` 把任何异常转成 `{"tool_error": true, "error": "..."}` 文本回给模型**（[tool_console.py:38](tool_console.py#L38)），不往上冒。名字对不上（`KeyError`）、参数不是合法 JSON（`JSONDecodeError`）、实现签名不匹配（`TypeError`）三条路都走到这里。模型能看见失败原因自己纠正，而不是把 REPL 打崩——循环层只捕获 `KeyboardInterrupt` / `EOFError`，不接别的。**别在 `tool_run` 里改成 re-raise。**
- **`tool_error` 是保留键，`impls` 的返回值里不许用。** 它存在的理由**不是给模型看的**（`{"error": ...}` 那个键模型本来就够读），而是给客户端留一个**带外**信号：否则"工具执行失败了"和"工具成功返回了一份含 `error` 键的数据"输出完全同形，谁也分不出来。约定是——**只有失败路径带这个键，成功路径不带，"没有它"即成功**。将来真要把它提升成 Anthropic 的 `is_error` 字段，靠的就是这个键，`tool_run` 的签名不用再动。

## 已知缺口

- **没有权限确认环节：工具一旦注册就直执行，不会先问用户。** 这是目前最该补的一条——`tool_run` 已经有异常兜底，但一个能读文件 / 发请求的工具注册进来就立刻可被模型调用。
- 只有一个样例工具，返回值是写死的假数据。真工具要处理的事（超时、分页、输出过大要截断）都还没有先例。
- 工具结果是整段塞进 context 的（[../control_loop.py:99](../control_loop.py#L99)），没有长度上限，一个话痨工具能把上下文顶爆。
