# ANY

一个终端里的多轮 LLM 对话 REPL。核心是把 **Anthropic Messages API** 和 **OpenAI Responses API** 这两套完全不同的请求/响应形状，收敛到同一份协议后面，让对话循环不需要知道自己在跟谁说话。

## 特性

- **双 provider，一套循环**：[control_loop.py](src/control_loop.py) 只认协议，不认 provider。
- **流式输出**：默认逐字渲染，收尾换成 Markdown 终稿。
- **工具调用**：两家的信封差异（Anthropic 要包 `assistant`/`user` 两条消息并回传 thinking 块，OpenAI 是裸 item）由 wrapper 内部消化。
- **token / 缓存用量**：每轮打印上下文占用，两侧口径已对齐。
- **可插拔槽位**：模型/强度选择器、会话存取、系统提示词文件三处都由仓库根的 [links.json](links.json) 指向，默认实现在 `src/` 里硬编码；json 缺失或坏掉只会逐项退回默认。
- **具名会话**：一个会话一个文件，启动时选旧会话续聊或新建一个（新建要取名字），之后自动存盘（见下「会话文件」）。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

配置文件是 `src/api_keys.json`，**已被 .gitignore 忽略**，需要自己创建：

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

字段说明：

| 字段 | 含义 |
|---|---|
| `current_provider` | 当前使用 `providers` 里的哪一项 |
| `providers.<名>.API` | **选择用哪个 wrapper**，取 `"messages"` 或 `"responses"`。注意这是 API 种类，不是厂商名——上例里厂商叫 deepseek，但走的是 Anthropic 兼容端点 |
| `providers.<名>.base_url` | 端点地址。任何提供 Anthropic / OpenAI 兼容接口的服务都能接 |
| `providers.<名>.api_key` | 密钥 |
| `models[].context_window` | 上下文窗口，用于计算占用百分比 |
| `models[].max_output_tokens` | 单次输出上限，直接作为 `max_tokens` / `max_output_tokens` 传出 |
| `models[].efforts` | 可选的推理强度列表，会作为 `output_config.effort` / `reasoning.effort` 传出 |

> `efforts` 里出现 `none` 不会报错，但 Anthropic 官方文档的枚举是 `low` / `medium` / `high` / `xhigh` / `max`，没有 `none`。这是第三方兼容端点的自由度，具体是否被接受取决于你的服务商——**deepseek 的 Anthropic 兼容端点实测接受 `none`**（2026-09-29），换个服务商要重新验。

> 配置路径是**相对于当前工作目录**写死的（[utils.py:8](src/utils.py#L8) 的 `API_KEYS_FILE = "src/api_keys.json"`），所以必须**从仓库根目录**运行。`links.json`、系统提示词文件、会话文件同理。

### links.json（可插拔槽位）

仓库根的 [links.json](links.json) 把三个槽位指向具体实现，默认值就是仓库自带的实现，所以这份文件原样入库：

```json
{
  "choosing_module": "src.default_choosing",
  "saver_loader_module": "src.default_saver_loader",
  "system_prompt_file": "src/default_system_prompt.md"
}
```

| 键 | 指向什么 | 默认 |
|---|---|---|
| `choosing_module` | 模型/推理强度选择器模块，需导出 `model_choose(models)` 和 `reasoning_choose(model)`；返回 `None` 表示用户取消 | `src.default_choosing` |
| `saver_loader_module` | 会话存取模块，需导出 `choose_session()` → 名字（`None` = 取消）、`load_session(name, provider_meta)` → 存档 dict 或 `None`（没有就新建）、`save_session(name, context, model, effort, provider_meta)` | `src.default_saver_loader` |
| `system_prompt_file` | 追加在日期行之后的系统提示词文件 | `src/default_system_prompt.md` |

三个键都可省。**缺失、JSON 损坏、指向不存在的模块/文件、模块缺函数，都逐项退回默认**并各打一行 dim，不会崩在启动上。自定义模块按上面的函数名实现即可（模块路径写成 `src.xxx` 或仓库根下的 `xxx`，都从仓库根运行）。

### 系统提示词

系统提示词 = `You are <模型名>. Today is <日期>` + 换行 + `default_system_prompt.md` 的内容。默认文件是空的，此时行为与没有这个功能时完全一致；往里面写什么都会原样进提示词。给 `control_loop` 显式传 `system_prompt` 参数时不受影响。

### 会话文件

一个会话一个文件，放在仓库根的 `sessions/<名字>.json`，**整个目录已 gitignore**，明文保存整段对话。

启动时先选会话：

- 已有会话按最近改动倒序列出，最后一项是「New session…」；一个会话都没有时不弹选择器，直接问名字。
- 选旧会话就续上：档里的模型和强度仍在当前配置里，则跳过两个选择器直接进入对话；否则正常选，但历史保留。
- 新建会话要取名字。规则宽松：只拦路径分隔符、空名、控制字符、超长，中文/空格/符号都能用；打的名字和已有会话重名就当续上那个会话。

之后全部自动：每轮模型回复后整篇落盘，`Ctrl-C` / `Ctrl-D` 退出前再落一次（被打断的那轮留下的一条无回复的用户消息也会存下来）。写盘是原子的（先写 `.tmp` 再 `os.replace`），中断不会写坏文件。想删掉某个会话就直接删它的文件。

存档里记了 provider 名和 API 种类。**API 种类变了**（`messages` ↔ `responses`，两边的消息信封形状根本不兼容）不会加载：旧档改名成 `<名字>.json.bak`，全新开始；**只是 provider 改名**（同一种 API）则提醒一句后照常续上。格式版本对不上同理留 `.bak`。

显式给 `control_loop` 传 `context` 参数的调用方不进会话流程：不问名字，也不落盘。

## 运行

```bash
python main.py
```

先选会话（续旧或新建并取名），再按需选模型、选推理强度，然后进入对话。`Ctrl-C` 或 `Ctrl-D` 退出。

## 项目结构

```
main.py                     读配置 → 按 API 字段选 wrapper → 进循环
links.json                  可插拔槽位的指针文件（见上「配置」）
src/
  control_loop.py           REPL 主循环：流式渲染、工具轮、用量显示、会话续接
  default_choosing.py       默认的模型/强度选择器（choosing_module 槽位）
  default_saver_loader.py   默认的具名会话存取，原子写盘（saver_loader_module 槽位）
  default_system_prompt.md  追加在日期行之后的系统提示词（默认空）
  utils.py                  配置/links 读取、槽位解析、rich console、questionary 选择器
  llm/
    protocol.py             三份协议：llm_protocol / response_protocol / stream_protocol
    messages_llm.py         Anthropic Messages API 包装
    responses_llm.py        OpenAI Responses API 包装
  tools/
    tool_console.py         工具注册表与执行（含一个样例工具，见下）
sessions/                   会话存档目录，一个会话一个文件（自动生成，已 gitignore，见上）
```

## 架构

分三层，边界很清楚：

**1. 协议层**（[protocol.py](src/llm/protocol.py)）
三份 `Protocol`：`llm_protocol` 描述 wrapper 本身（`start_stream` / `stream_complete`，以及把中立工具定义转成线上形状的 `tool_definitions`），`response_protocol` 描述一个"响应对象"该长什么样（`output_text`、`tool_calls`、`usage`、`stop_reason` …），`stream_protocol` 描述一个"流对象"（产出文本增量、可关闭）。两个 wrapper 都**显式继承**协议，漏实现任何成员会在实例化时 `TypeError`。

**2. wrapper 层**（[messages_llm.py](src/llm/messages_llm.py) / [responses_llm.py](src/llm/responses_llm.py)）
两个类提供形状相同的入口：

- `get_response(...)` —— 阻塞式，返回响应包装对象
- `start_stream(...)` —— 发起流式请求，返回流包装对象
- `stream_complete(stream)` —— 收尾，返回同一套响应包装对象
- `tool_definitions(tools)` —— 把**中立形状**的工具定义转成本家线上形状（Anthropic 把 `parameters` 改名成 `input_schema`，OpenAI Responses 外面套一层 `{"type": "function"}`）。`_params()` 内部会调它，所以调用方一路传中立的即可，不要预先转换。

同一个 `_params()` 构造两条路的请求体，保证两者不会悄悄分叉。

**3. 循环层**（[control_loop.py](src/control_loop.py)）
只调上面三个入口，用 `for text in stream` 拿增量渲染，用协议方法取工具调用、拼下一轮上下文。它不知道也不关心当前是哪个 provider。选型、存档、系统提示词三处都走可插拔槽位（[default_choosing.py](src/default_choosing.py) / [default_saver_loader.py](src/default_saver_loader.py) / [default_system_prompt.md](src/default_system_prompt.md)）；provider 身份只作为一个不透明参数穿过循环层，判断存档能不能续接的比较发生在存档模块内部，循环层里没有任何按 provider 分叉的地方。

## 已知限制

- **工具表里只有一个样例工具。** [tool_console.py](src/tools/tool_console.py) 里的 `get_weather` 返回写死的假数据：链路已接通（注册表存中立形状，线上形状由 wrapper 转换），但还没有真工具，也没有权限确认——注册进来就直执行。工具结果整段进 context，没有长度上限。
- **没有测试。** 没有测试框架，验证靠临时脚本。
- **只有 Anthropic 那条路端到端验过。** OpenAI 那条目前只有静态检查——配置里没有可用的 OpenAI 兼容 provider。
- **`get_response` 对超大输出上限不可用。** 原因见 [src/llm/AGENTS.md](src/llm/AGENTS.md) 的「Per provider」小节里 Anthropic 那一条。
- **会话文件是明文且不设上限。** `sessions/<名字>.json` 里是原样的对话内容（可能包含你粘贴过的密钥），并且每轮整篇重写、无限增长；超出模型上下文窗口时由端点报错，程序不会自动截断。要换存储方式就换 `saver_loader_module` 槽位。
- **续接存档的兼容性取决于端点。** 存档里的 thinking 块连同签名原样回传，换 provider 或换端点后能不能被接受由对方决定（换 API 种类时不会续接，见上「会话文件」）。
