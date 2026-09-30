# ANY

一个终端里的多轮 LLM 对话 REPL。核心是把 **Anthropic Messages API** 和 **OpenAI Responses API** 这两套完全不同的请求/响应形状，收敛到同一份协议后面，让对话循环不需要知道自己在跟谁说话。

## 特性

- **双 provider，一套循环**：[control_loop.py](src/control_loop.py) 只认协议，不认 provider。
- **流式输出**：默认逐字渲染，收尾换成 Markdown 终稿。
- **工具调用**：两家的信封差异（Anthropic 要包 `assistant`/`user` 两条消息并回传 thinking 块，OpenAI 是裸 item）由 wrapper 内部消化。
- **token / 缓存用量**：每轮打印上下文占用，两侧口径已对齐。

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

> 配置路径是**相对于当前工作目录**写死的（[utils.py:5](src/utils.py#L5) 的 `API_KEYS_FILE = "src/api_keys.json"`），所以必须**从仓库根目录**运行。

## 运行

```bash
python main.py
```

会依次让你选模型、选推理强度，然后进入对话。`Ctrl-C` 或 `Ctrl-D` 退出。

## 项目结构

```
main.py                     读配置 → 按 API 字段选 wrapper → 进循环
src/
  control_loop.py           REPL 主循环：输入、流式渲染、工具轮、用量显示
  utils.py                  配置读取、rich console、questionary 选择器
  llm/
    protocol.py             三份协议：llm_protocol / response_protocol / stream_protocol
    messages_llm.py         Anthropic Messages API 包装
    responses_llm.py        OpenAI Responses API 包装
  tools/
    tool_console.py         工具注册表与执行（含一个样例工具，见下）
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
只调上面三个入口，用 `for text in stream` 拿增量渲染，用协议方法取工具调用、拼下一轮上下文。它不知道也不关心当前是哪个 provider。

## 已知限制

- **工具表里只有一个样例工具。** [tool_console.py](src/tools/tool_console.py) 里的 `get_weather` 返回写死的假数据：链路已接通（注册表存中立形状，线上形状由 wrapper 转换），但还没有真工具，也没有权限确认——注册进来就直执行。工具结果整段进 context，没有长度上限。
- **没有测试。** 没有测试框架，验证靠临时脚本。
- **只有 Anthropic 那条路端到端验过。** OpenAI 那条目前只有静态检查——配置里没有可用的 OpenAI 兼容 provider。
- **`get_response` 对超大输出上限不可用。** 原因见 [src/llm/AGENTS.md](src/llm/AGENTS.md) 的「Anthropic 侧特有的坑」。
