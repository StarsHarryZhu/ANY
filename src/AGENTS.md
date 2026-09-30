# AGENTS.md

`src/` 是全部源码，分三层：**循环层**（本目录两个 `.py`）→ **wrapper 层**（[llm/](llm/)）→ **协议层**（[llm/protocol.py](llm/protocol.py)）。调用方向严格单向：循环层只认协议，不 import 任何 SDK，也不 import 具体的 wrapper 类。

## 布局

```
control_loop.py  REPL 主循环：选模型/强度 → 取输入 → 流式取回复 → 渲染 → 工具轮 → 用量
utils.py         配置读取、rich console 单例、questionary 选择器
api_keys.json    配置；gitignore 忽略，需自建，schema 见 ../README.md
llm/             三份协议 + 两个 provider 的 SDK 包装（见 llm/AGENTS.md）
tools/           工具注册表与执行（见 tools/AGENTS.md）
```

`src/`、`src/llm/`、`src/tools/` 都**没有 `__init__.py`**，靠 PEP 420 命名空间包工作。新增子包保持这个约定，但别依赖包的 `__init__` 做初始化。

## 约定

- **`control_loop.py` 禁止出现 provider 分支。** 这个文件不知道也不该知道当前是 Anthropic 还是 OpenAI，所有形状差异由 [llm/](llm/) 抹平。`llm` 参数要的就是 [llm/protocol.py](llm/protocol.py) 里的 `llm_protocol`，两个 wrapper 都显式继承了它；但**不要 import 具体 wrapper 类做 isinstance 判断**——协议是用来约束实现的，不是用来在调用方分类的。
- **Live 按轮次开合。** 每轮都要完整 `live.stop()` 之后再开下一个（[control_loop.py:60](control_loop.py#L60)）。`Console.set_live` 在已有 Live 时返回 `False`，新 Live 会**静默退化成 `_nested`**，症状是 `start()` 不生效、只有 `stop()` 时才打印一次。
- **Live 活动期间不能 `console.input()`，也不能随便 `print`。** 期间 `sys.stdout` 被换成 `FileProxy`，实测输出会被吞掉。工具行的打印安排在 Live 拆掉之后，就是这个原因。
- **中断路径刻意不调 `stream_complete`。** 被 Ctrl-C 打断的 anthropic 轮次会产出 thinking 块没有配对签名的残缺消息，塞进 `context` 后下一轮会被服务端拒；丢掉这半轮是正确行为（[control_loop.py:52-54](control_loop.py#L52-L54) 有注释）。**别在这里"顺手补个 drain"。** 代价是中断留下一条没有回复的 user 消息，两家都能容忍连续同角色消息（会合并）。
- **两层嵌套 `finally` 不要拍平**（[control_loop.py:74-81](control_loop.py#L74-L81)）：外层 `live.stop()`、内层 `stream.close()`，任一清理抛异常都不会吃掉另一个。Ctrl-C 后光标能恢复，靠的就是 `live.stop()` 一定执行。
- **`STREAM_TAIL`（[control_loop.py:12](control_loop.py#L12)）不能删。** Live 默认 `vertical_overflow="ellipsis"`，内容超屏时取 `lines[:height-1]` 补省略号，即**裁底部、锁顶部**——全文渲染会让长回复看着像卡住。终稿不受影响，`stop()` 会把 overflow 切成 `"visible"`。
- **状态行两处都必须是 `used_context`，不是 `total_tokens`。** 那一行是 f-string 里出现两次的同一个量（分子和百分比），改一处漏一处会显示成"1234 / 384000 (45.2%)"这种自相矛盾的输出。选 `used_context` 是因为 `total_tokens` 在 Anthropic 上不含缓存读写，而缓存命中的部分正是长会话里上下文的大头——实测构造样例里少报 61 倍，且越到后面错得越多。口径差异详见 [llm/AGENTS.md](llm/AGENTS.md)。
- **`utils.py` 的 `console` 是模块级单例，必须带 `highlight=False`**（[utils.py:8](utils.py#L8)）。去掉它 rich 会给数字/字符串自动上色，模型输出被随机染色。所有打印都走这个对象，不要另建 `Console()`——Live 状态挂在 console 的 `_live_stack` 上，多个 console 各管各的。
- **`utils.py` 的 `load_api_config()` 吞掉 `FileNotFoundError` 返回 `{}`**，不做任何校验。配置缺失不会在这里报错，而是下游 `KeyError`。
- **`utils.py` 的 `select()` 的 `key` 参数是死参数**（[utils.py:24](utils.py#L24)），收下但从不使用——调用方都是先 `to_questionary_type(choices, key)` 转换好再传进来。新增选择器沿用这个两步走法，取消时返回 `None`，调用方要判空。
- **`api_keys.json` 的结构变更要同步三处**：[README.md](../README.md) 的 schema 表格、[main.py](../main.py) 的读取逻辑、本文件。

## 检查

```sh
python main.py                    # 端到端；需先自建 src/api_keys.json
```

- **渲染效果必须在真实终端里看。** 非 tty（管道、重定向、`| tee`）下 rich 会把渲染推迟到 `stop()` 时打印一次，没有任何控制码，看不出真实观感。
- **中断路径**：用代理流对象在第 N 个增量后抛 `KeyboardInterrupt`，断言 `stream.close()` 被调用过、`console._live_stack` 已清空、无 traceback、`context` 里没有半截 assistant 消息。
- **驱动整个循环做端到端测试**：打桩 `control_loop` 模块里的 `select` 和 `console.input`（`console` 就是 [utils.py](utils.py) 里那个对象，改它的方法即可）。
