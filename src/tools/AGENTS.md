# AGENTS.md

工具的定义注册与执行。目前只有控制台一个后端，被 [../control_loop.py](../control_loop.py) 以固定三步使用：构造 → `tool_define()` 传给 `start_stream` → 拿到工具调用后逐个 `tool_run()`。

## 布局

```
tool_console.py   工具注册表与执行：self.tools（定义）/ self.impls（实现）/ tool_define / tool_run
```

## 约定

- **`self.tools` 和 `self.impls` 目前都是空的**（[tool_console.py:6-7](tool_console.py#L6-L7)），`tool_define()` 恒返回 `[]`，两个 wrapper 拿到空列表都会省略 `tools` 参数，所以**工具调用链路目前跑不到**——但代码路径是通的，实测可用。注册工具就是往这两个容器里填。
- **工具定义 schema 分 provider**，这是本文件最容易踩的坑：

  | provider | 形状 |
  |---|---|
  | Anthropic | `{"name", "description", "input_schema": {...}}` |
  | OpenAI Responses | `{"type": "function", "name", "description", "parameters": {...}}` |

  [tool_define()](tool_console.py#L10) 里注释掉的那段**是 OpenAI 形状**，直接取消注释拿给 Anthropic 端点会被拒。
- **`tool_run` 的 `arguments` 是 JSON 字符串，不是 dict。** 协议层已统一过：`tool_call_arguments()` 保证两侧都吐 JSON 字符串（Anthropic 的 `call.input` 本来是 dict，wrapper 会 `dumps` 一次），这里直接 `json.loads` 即可，不要额外判类型。
- **`impls` 的键必须和 `tools` 里的 `name` 完全一致。** 对不上不会在注册时报错，而是在 `tool_run` 里 `KeyError`。
- **返回值会被 `json.dumps(..., ensure_ascii=False)` 序列化**，实现要么返回可 JSON 序列化的值，要么自己返回序列化好的字符串。

## 已知缺口

- 没有任何工具注册。第一个工具落地时要做的：填 `impls` 和 `tools`，并按上表写对形状。
- **`tool_run` 没有异常处理。** 工具抛异常、名字对不上、返回值不可序列化，三种情况都会直接冒到循环层，而 [../control_loop.py](../control_loop.py) 只捕获 `KeyboardInterrupt` / `EOFError`，会带 traceback 崩掉 REPL。要稳，应该在 `tool_run` 里包一层，把失败转成一条错误文本返回给模型（让模型自己看到并纠正），而不是让进程挂掉。
- 没有权限确认环节：工具一旦注册就直执行，不会先问用户。
