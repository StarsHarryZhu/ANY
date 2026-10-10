import importlib
import json
import questionary
from rich.console import Console

# 相对当前工作目录写死：只从仓库根目录运行才对。否则 FileNotFoundError 会被吞成
# {}，问题推迟到下游的 KeyError。
API_KEYS_FILE = "configs/api_keys.json"

# 可插拔槽位的指针文件。所有 .json 配置都收在 configs/ 下，src/ 里只剩代码和系统提示词
# 那个 .md——但路径的规则没变：照样相对 CWD，照样只从仓库根运行才对。
# 模块值写成 "src.default_choosing" 这种形式：从仓库根运行时能导入，src 是命名空间包。
# 三个键都可省，缺省/坏掉各自退回内置默认（默认值就是这里的常量和 control_loop 里的模块路径）。
LINKS_FILE = "configs/links.json"

# 系统提示词文件的内置默认路径；links.json 的 system_prompt_file 可以覆盖它。
# 唯一的非 .json 配置，所以它留在 src/ 下。
SYSTEM_PROMPT_FILE = "src/default_system_prompt.md"

# 可用的工具预置清单。它列的是 preset.json 的具体路径（可跨多个目录），这张表就是启动时
# 预置选择器的菜单。清单本身住在 presets/ 下，跟它列的预置放一起。
PRESETS_DIR_FILE = "configs/presets/presets_dir.json"

# 预置清单缺失/坏掉时的内置默认＝仓库自带的"全量模式"。
DEFAULT_PRESET_FILES = ("configs/presets/full/preset.json",)

# 工具表：模块路径 -> 类名。它是工具的唯一来源，代码里不再有硬编码的工具清单——留一份内置
# 默认就等于又有了第二份登记表，所以这里没有默认值可退。
TOOLS_FILE = "configs/tools.json"

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

def load_preset_files() -> list:
    # 与 load_links 同一套降级，只有一处差别：presets_dir.json 是随仓库发的，缺了不是常态
    # （links.json 在全新克隆里缺席才是常态），所以文件不存在也打一行 dim，并说明退回了什么。
    # 只负责读出一张路径表：不检查文件是否存在、也不读 preset.json——路径一份份坏掉要逐个报，
    # 那是工具层 _load_presets 的活。
    try:
        with open(PRESETS_DIR_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        console.print(f"[dim]{PRESETS_DIR_FILE} not found; using {list(DEFAULT_PRESET_FILES)!r}[/dim]")
        return list(DEFAULT_PRESET_FILES)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        console.print(f"[dim]{PRESETS_DIR_FILE} unreadable ({type(error).__name__}: {error}); using {list(DEFAULT_PRESET_FILES)!r}[/dim]")
        return list(DEFAULT_PRESET_FILES)
    if not isinstance(config, dict):
        console.print(f"[dim]{PRESETS_DIR_FILE} is not a JSON object; using {list(DEFAULT_PRESET_FILES)!r}[/dim]")
        return list(DEFAULT_PRESET_FILES)
    paths = config.get("presets_dir")
    # 单个字符串按只有一项处理：手写时不必为了一个预置套一层数组。
    # 空数组是合法的"一份都不要"（下面工具层会因此不过滤），不是坏配置。
    if isinstance(paths, str) and paths:
        return [paths]
    if isinstance(paths, list) and all(isinstance(item, str) and item for item in paths):
        return paths
    console.print(f"[dim]{PRESETS_DIR_FILE}: 'presets_dir' must be a path or a list of paths, got {paths!r}; using {list(DEFAULT_PRESET_FILES)!r}[/dim]")
    return list(DEFAULT_PRESET_FILES)


def load_tools() -> list:
    # 返回 [(模块路径, 类名), ...]，顺序＝文件里的书写顺序（dict 保序，工具给模型的顺序因此
    # 由 tools.json 决定）。只读配置，不导入任何模块：路径指错了要一行行报，那是工具层的活。
    # 降级一律返回空表：工具层的失败方向只能是"少几个工具"。文件坏了就凭空多出工具来才是灾难。
    try:
        with open(TOOLS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        console.print(f"[dim]{TOOLS_FILE} not found; no tools will be registered[/dim]")
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        console.print(f"[dim]{TOOLS_FILE} unreadable ({type(error).__name__}: {error}); no tools will be registered[/dim]")
        return []
    if not isinstance(config, dict):
        # 与下面 'tools' 那条分开报：顶层不是对象时 config.get 根本无从谈起，报成
        # "'tools' ... got None" 会把人往错的方向引（同 load_links 的分法）。
        console.print(f"[dim]{TOOLS_FILE} is not a JSON object; no tools will be registered[/dim]")
        return []
    tools = config.get("tools")
    if not isinstance(tools, dict):
        console.print(f"[dim]{TOOLS_FILE}: 'tools' must be an object of module-path -> class-name, got {tools!r}; no tools will be registered[/dim]")
        return []
    entries = []
    bad = []
    for module_path, class_name in tools.items():
        if isinstance(module_path, str) and module_path and isinstance(class_name, str) and class_name:
            entries.append((module_path, class_name))
        else:
            bad.append((module_path, class_name))
    if bad:
        # 坏条目攒成一行，不是一条一行：坏文件只该吵一次（同 load_links 的理由）。
        console.print(f"[dim]{TOOLS_FILE}: skipped {bad!r} (path and class must both be non-empty strings)[/dim]")
    if not entries:
        console.print(f"[dim]{TOOLS_FILE}: no usable tool entry; no tools will be registered[/dim]")
    return entries


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






