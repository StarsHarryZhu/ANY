# AGENTS.md

ANY 是终端里的多轮 LLM 对话 REPL，把 Anthropic Messages API 与 OpenAI Responses API 收敛到同一份协议后面：**循环层不认 provider，只认协议**。改代码前先读 [src/AGENTS.md](src/AGENTS.md)，动 wrapper 前先读 [src/llm/AGENTS.md](src/llm/AGENTS.md)。

## 仓库布局

```
main.py                  入口：读配置 → 按 API 字段选 wrapper → 交给 control_loop
requirements.txt         四项依赖，全部精确锁版本
.gitignore               忽略 api_keys.json / .env / .venv / _reference_api_respond
README.md                面向使用者：安装、配置 schema、运行、已知限制
src/                     全部源码（见 src/AGENTS.md）
  llm/                     两份协议 + 两个 provider 的 SDK 包装（见 src/llm/AGENTS.md）
  tools/                   工具注册表与执行（见 src/tools/AGENTS.md）
_reference_api_respond/  两份手工存的原始响应样本；代码不引用它，已 gitignore
.venv/                   Python 3.14 虚拟环境
```

## 命令

```sh
pip install -r requirements.txt   # anthropic==1.5.0 openai==3.13.0 questionary==2.1.1 rich==15.0.0
python main.py                    # 必须从仓库根目录运行
```

## 约定

- **provider 差异只能待在 wrapper 里**：循环层出现 `if provider == ...` 就说明该往 wrapper 加方法，而不是在调用方分叉。
- **信封由 wrapper 决定，调用方不拼**：工具轮追加进 context 的整段只能来自 `tool_continuation()`，两家形状相反（Anthropic 要包两条消息，OpenAI 是裸 item）。
- **阻塞与流式共用请求体构造**：两个 wrapper 各有一个 `_params()`，`get_response` 与 `start_stream` 都必须走它，否则"同一个请求"在两条路下会悄悄分叉。
- **必须从仓库根目录运行**：配置路径是 CWD 相对写死的（[utils.py:5](src/utils.py#L5)），从别处运行会 `FileNotFoundError` 被吞成空字典，再在下游 `KeyError`。
- **`main.py` 新增 provider 必须补 `else`**：现在只有 `if/elif`（[main.py:11-14](main.py#L11-L14)），`API` 字段写错不会报配置错误，而是 `llm` 未绑定、下一行 `NameError`。
- **升级 SDK 版本前，先读各层 AGENTS.md 里标注的版本相关行为**：流对象的内部结构、rich Live 的 overflow 策略等，都是从当前版本实测出来的，换版本可能失效，改完要同步文档。
- **没有测试框架，也没有测试文件**：改动后按各层 AGENTS.md 的「检查」一节内联验证，不要假设有测试可跑。

## 密钥

`src/api_keys.json` 不在版本控制里，需自建，schema 见 [README.md](README.md)。**任何情况下不要提交、不要贴进 issue、不要写进文档示例**，示例一律用 `sk-...` 占位。

`.gitignore` 的注释声称存在一个可提交的模板 `api_keys.example.json`，**该文件目前并不存在**——要么补上它，要么删掉那句注释。

## 已知缺口

- 工具表为空，工具调用链路目前跑不到（代码路径是通的，实测可用）。见 [src/tools/AGENTS.md](src/tools/AGENTS.md)。
- OpenAI 那条路没有端到端验证过，只有静态与构造期检查。
- `get_response` 对当前配置的 `max_output_tokens` 不可用。见 [src/llm/AGENTS.md](src/llm/AGENTS.md)。
