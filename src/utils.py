import importlib
import json
import questionary
from rich.console import Console

# 相对当前工作目录写死：只从仓库根目录运行才对。否则 FileNotFoundError 会被吞成
# {}，问题推迟到下游的 KeyError。
API_KEYS_FILE = "src/api_keys.json"

# 可插拔槽位的指针文件，在仓库根目录、不在 src/ 下。模块值写成 "src.default_choosing"
# 这种形式：从仓库根运行时能导入，src 是命名空间包。三个键都可省，缺省/坏掉各自退回
# 内置默认（默认值就是这里两个常量和 control_loop 里的模块路径）。
LINKS_FILE = "links.json"

# 系统提示词文件的内置默认路径；links.json 的 system_prompt_file 可以覆盖它。
SYSTEM_PROMPT_FILE = "src/default_system_prompt.md"

# highlight=False: 关掉 rich 对数字/字符串的自动高亮，否则模型输出会被随机染色。
# 全仓库共用这一个 console：Live 状态挂在它的 _live_stack 上，另建 Console() 会各管
# 各的，live.stop() 清理到的就不是同一个。
console = Console(highlight=False)

def load_api_config():
    # 配置缺失不在这里报错：吞掉 FileNotFoundError 返回 {}，不做任何校验。
    try:
        with open(API_KEYS_FILE, "r") as f:
            api_config = json.load(f)
    except FileNotFoundError:
        api_config = {}
    return api_config


def load_links() -> dict:
    # 与 load_api_config 的差别是有意的：api_keys.json 是必需配置，只吞 FileNotFoundError，
    # 让问题在下游的 KeyError 暴露；links.json 只是可选覆盖层，坏掉必须"惰性失效"退回全
    # 默认，所以 JSONDecodeError、非对象也一并吞掉。文件不存在是最常见的情况（全新克隆），
    # 静默；能读到却读不出来才是异常，打一行 dim。
    # 由 control_loop 只调一次、结果往下传：坏文件因此只警告一次，不是每个槽位报一遍。
    try:
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            links = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        console.print(f"[dim]links.json unreadable ({type(error).__name__}: {error}); using built-in defaults[/dim]")
        return {}
    if not isinstance(links, dict):
        console.print("[dim]links.json is not a JSON object; using built-in defaults[/dim]")
        return {}
    return links


def resolve_module(links: dict, slot: str, default_module: str, members: list):
    # 槽位 -> 模块：links 里的值必须是模块路径字符串，导入后还得带齐 members 列的属性，
    # 否则算"链接坏了"——打一行 dim 后退回 default_module。
    # 捕获 Exception 是刻意的：路径写错、目标模块自己有 import 期错误，都只是配置问题，
    # 不能拖垮启动。default_module 是仓库自带代码，它导入失败或缺属性属于代码 bug，照常抛。
    path = links.get(slot)
    if path is not None:
        if not isinstance(path, str) or not path:
            console.print(f"[dim]links.json: {slot!r} must be a module-path string, got {path!r}; using {default_module!r}[/dim]")
        else:
            try:
                module = importlib.import_module(path)
                missing = [name for name in members if not hasattr(module, name)]
                if missing:
                    raise AttributeError(f"missing {', '.join(missing)}")
                return module
            except Exception as error:
                console.print(f"[dim]links.json: {slot!r} -> {path!r} unusable ({type(error).__name__}: {error}); using {default_module!r}[/dim]")
    module = importlib.import_module(default_module)
    for name in members:
        # 默认模块的属性检查只为报错：缺了就是仓库代码 bug，在这里炸比下游 AttributeError 清楚。
        getattr(module, name)
    return module


def load_system_prompt(links: dict) -> str:
    # 外置系统提示词文件。路径指错、文件被删、读不出来，都退回空串（＝与没有这个功能时
    # 行为一致），只打一行 dim。
    # strip 两端空白：空文件因此与"完全不加"等价，调用方只在非空时才追加。
    path = links.get("system_prompt_file")
    if path is not None and (not isinstance(path, str) or not path):
        console.print(f"[dim]links.json: 'system_prompt_file' must be a path string, got {path!r}; using {SYSTEM_PROMPT_FILE!r}[/dim]")
        path = None
    if path is None:
        path = SYSTEM_PROMPT_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError) as error:
        console.print(f"[dim]system prompt file {path!r} unreadable ({type(error).__name__}: {error}); continuing without it[/dim]")
        return ""

def to_questionary_type(choices: list, key: str) -> list:
    return [
        {"name": str(item[key]), "value": item} if isinstance(item, dict) else item
        for item in choices
    ]

def select(choices: list, message: str, key: str = "name"):
    # key 是死参数：收下但从不用，调用方都是先用 to_questionary_type(choices, key)
    # 转换好再传进来。新增选择器沿用这个两步走法。取消时返回 None，调用方要判空。
    return questionary.select(message, choices).ask()


def ask_text(message: str):
    # 与 select 同策：取消（Esc / Ctrl-C）返回 None，调用方判空。
    return questionary.text(message).ask()






