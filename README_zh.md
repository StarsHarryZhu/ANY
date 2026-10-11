# ANY

> 一个终端里的多轮 LLM 对话 REPL，也是一次 vibe coding 实验。

[English](README.md)

ANY 把 Anthropic Messages API 和 OpenAI Responses API 收敛到同一个协议接缝后面：
控制循环只认识协议，从不知道自己在跟哪个厂商说话。整个项目基本是在对话里由 LLM
写出来的——这个仓库存在的意义，是看看这样能走多远。

它不是一个产品。没有发布到 PyPI，没有 LICENSE，没有测试，接口随时会变。

## 它能做什么

- 终端里的流式多轮对话：回答边生成边渲染，结束后换成完整 Markdown。
- 两个厂商、两套 API，循环层不做任何 provider 分支。
- 工具调用：两边工具回合信封的差异（Anthropic 包 `assistant`/`user` 消息并带回
  thinking 块，OpenAI 用裸 item）全部由 wrapper 吸收。
- 具名会话：一个会话一个文件，启动时可以挑一个旧的续聊，也可以新建；每轮自动保存，
  恢复时把历史重放到终端。
- 三个可插拔槽位：模型/推理档选择器、会话存储、系统提示词文件，都由
  `configs/links.json` 指向；缺文件、坏文件都各自兜底，不会拖垮启动。
- 启动时的工具预置：`configs/presets/` 决定这次会话能用哪些工具。

## 状态：哪些验过，哪些没有

| 已经实测 | 没有实测 |
| --- | --- |
| `messages` 路径端到端，含工具回合（对一个第三方 Anthropic 兼容端点） | `responses` 路径（OpenAI）：写完了，只做过静态检查和构造检查，没跑过真实端点 |
| 槽位解析与三处兜底 | 恢复一个**以工具回合结尾**的存档：重放的块还没被真实端点接受过 |
| 会话保存 / 恢复的往返 | `get_response` 在配置的输出上限下不可用 |
| 工具层：两个工具、各自的失败分支、预置矩阵（手工过了一遍） | |

## 依赖

Python 3.14，六个固定版本的依赖，见 [requirements.txt](requirements.txt)。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

需要自己创建 `configs/api_keys.json`（已被 gitignore）。最小可用形态：

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

- `API` 选的是 wrapper，取值 `"messages"` 或 `"responses"`——这是 API 的种类，不是
  厂商；一个兼容端点两个都可能提供。
- `efforts` 里的档位直接透传给端点。Anthropic 官方枚举是
  `low`/`medium`/`high`/`xhigh`/`max`，别的端点接受什么得自己试。
- 所有配置路径都按 CWD 硬编码，所以**必须在仓库根目录运行**。

## 运行

```bash
python main.py
```

启动顺序：挑会话 → 挑模型 → 挑推理档 → 挑工具预置 → 开始聊。`Ctrl-C` / `Ctrl-D` 退出。

## 目录

```
main.py                  入口：读配置，按 API 字段分发到对应 wrapper
configs/                 所有 .json 配置（CWD 相对）
  links.json               三个可插拔槽位的指针
  tools.json               工具表：模块路径 -> 类名，工具的唯一来源
  presets/                 工具预置，presets_dir.json 就是启动菜单
  api_keys.json            主配置（gitignore，需自己创建）
src/                     全部源码
  control_loop.py          控制循环
  llm/                     协议 + 两个厂商 wrapper
  tools/                   工具注册与执行
sessions/                一个会话一个 JSON，gitignore 的明文用户数据
```

## 已知限制

- 工具执行前没有任何权限确认，注册完就能被调用。`current_location` 每次调用都会把你的
  出口 IP 发给第三方定位服务，不缓存；三个源串行兜底，最坏约 24 秒。
- IP 定位只到城市级；`ip-api.com` 免费档只支持 HTTP 且不可商用。
- 没有测试，没有测试框架，全靠手工验。
- 会话是明文、无上限的，每轮整份重写；超窗错误由端点抛出，不会自动截断。
- 恢复的历史能不能被端点接受，取决于它还认不认自己吐过的 thinking 签名。

## 文档

[AGENTS.md](AGENTS.md) 及 `src/` 下三份子文件是开发者向的事实来源：架构约束、目录
职责、当前进度都在那里。这份 README 只负责说清楚它是什么、能干什么、什么还没验过。
