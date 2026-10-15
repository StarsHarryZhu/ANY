import importlib
import json
import questionary
from rich.console import Console
from rich.text import Text

# 相对当前工作目录写死：只从仓库根目录运行才对。否则 FileNotFoundError 会被吞成
# {}，问题推迟到下游的 KeyError。
# 它没有格式号：这份文件是手写的必需配置，没有"内置默认"可退（见下面各文件的 *_FORMAT）。
API_KEYS_FILE = "configs/api_keys.json"

# 每份 .json 配置顶层的 "version" 必须等于这里对应的格式号，解析出来的文档才算认得。
# 各自独立，不共用一个数：改 tools.json 的形状只该作废 tools.json，不该逼着所有人把手上的
# links.json、commands.json、预置文件一次性重盖一遍。
# 规则只有一条：**改一份文件的形状时，在同一个改动里把它的格式号 +1，并给仓库里那份文件
# 重新盖章**。仓库里的五份都盖好了，测试矩阵（见 AGENTS.md）照着这个走。
# 这些格式号与 default_saver_loader 的 SESSION_FORMAT 是两套东西，别合并：那个管的是用户
# 数据（对不上就改名 .bak 留底），这些管的是配置（对不上就退回内置默认）。
# 版本对不上的待遇与"文件坏掉"完全一致：一行 dim，走该加载器原有的兜底。理由见
# config_version_problem()。

# 可插拔槽位的指针文件。所有 .json 配置都收在 configs/ 下，src/ 里只剩代码和系统提示词
# 那个 .md——但路径的规则没变：照样相对 CWD，照样只从仓库根运行才对。
# 模块值写成 "src.default_choosing" 这种形式：从仓库根运行时能导入，src 是命名空间包。
# 三个键都可省，缺省/坏掉各自退回内置默认（默认值就是这里的常量和 control_loop 里的模块路径）。
LINKS_FILE = "configs/links.json"
LINKS_FORMAT = 1

# 系统提示词文件的内置默认路径；links.json 的 system_prompt_file 可以覆盖它。
# 唯一的非 .json 配置，所以它留在 src/ 下。
# 它没有格式号，也不该有：一份自由文本没有"形状"可言，塞个版本标记进去还会毁掉"空文件
# 与没有这个功能逐字一致"这条性质（见 src/AGENTS.md）。
SYSTEM_PROMPT_FILE = "src/default_system_prompt.md"

# 可用的工具预置清单。它列的是 preset.json 的具体路径（可跨多个目录），这张表就是启动时
# 预置选择器的菜单。清单本身住在 presets/ 下，跟它列的预置放一起。
PRESETS_DIR_FILE = "configs/presets/presets_dir.json"
PRESETS_DIR_FORMAT = 1

# 预置清单缺失/坏掉时的内置默认＝仓库自带的"全量模式"。
# 它列的是路径，不是文档：这条路不检查格式（它返回的是路径表），预设文档的闸门在工具层
# 的 _load_presets——那里是唯一打开预置文件的地方，列出来的和这里兜底的都从那儿过。
DEFAULT_PRESET_FILES = ("configs/presets/full/preset.json",)

# 工具表：模块路径 -> 类名。它是工具的唯一来源，代码里不再有硬编码的工具清单——留一份内置
# 默认就等于又有了第二份登记表，所以这里没有默认值可退。
TOOLS_FILE = "configs/tools.json"
TOOLS_FORMAT = 1

# 斜杠指令表：命令名（含前导斜杠）-> 工具名。与 tools.json 同族，但读它的是循环层——
# 指令是循环层对输入的解读，不是工具层的东西（"循环层不认工具表"那条规则不受影响）。
COMMANDS_FILE = "configs/commands.json"
COMMANDS_FORMAT = 1

# highlight=False: 关掉 rich 对数字/字符串的自动高亮，否则模型输出会被随机染色。
# 全仓库共用这一个 console：Live 状态挂在它的 _live_stack 上，另建 Console() 会各管
# 各的，live.stop() 清理到的就不是同一个。
console = Console(highlight=False)


def note(message: str) -> None:
    # 一行 dim 提示的唯一写法。不要写成 console.print(f"[dim]{...}[/dim]")：提示里插进来的
    # 内容大多来自文件（版本号、坏条目、异常文本）或用户输入（会话名、模型名），rich 会把
    # 其中的方括号当标记解析，解析不了就抛 MarkupError——本该"打一行提示"的地方变成一次
    # 崩溃。实测：把 {"version": "[/dim]"} 写进 configs/links.json，每个加载器都会在打印
    # 自己那行提示时炸掉，兜底一行都执行不到。
    # Text 不做标记解析，插进来的内容因此带什么方括号都安全。
    console.print(Text(message, style="dim"))


def config_version_problem(version, expected: int):
    # 格式闸门的唯一判据。返回 None ＝版本认得，可以解析；否则返回一句给用户看的原因
    # （不含文件名、不含后果——那两样是调用方的措辞，各自不同）。
    #
    # 为什么不在这里打印、也不在这里抛：
    # - 打印的话，调用方自己的那行 dim（"...；退回内置默认"）会跟进来，同一个文件报两行，
    #   而"坏文件只该吵一次"是这个仓库反复写明的规矩。
    # - 抛的话，"配置问题绝不崩启动"就得靠每个调用点记得捕获来维持——那正是最容易漏、
    #   而仓库里又没有测试能兜住的东西。返回原因，让调用方打自己那一行、走自己的兜底。
    #
    # 缺字段与写错同等对待，都算"这份文件不是这份代码写的"。少一半检测力（把缺字段当作
    # v1）等于给未来埋一个误判：真升到 v2 时，没盖过章的老文件会被当成合法的 v1 用下去。
    #
    # bool 必须先挡：JSON 的 true 在 Python 里 == 1，不挡的话 {"version": true} 会静默过关；
    # 1.0 同理，字符串 "1" 则永远匹配不上。同一个坑在 _build_registry 挡工具 ID、
    # _entry_id 挡 preset 条目 ID 时各挡过一次。
    if version is None:
        return f"'version' is missing (expected {expected})"
    if isinstance(version, bool) or not isinstance(version, int):
        # 只回显标量：version 本该是个整数，别的形状可以任意深（JSON 能解出几万层嵌套），
        # 对它们 repr 不是打出一屏就是直接 RecursionError——而这里要说的只是"你写错了"。
        shown = repr(version) if isinstance(version, (bool, float, str)) else f"a {type(version).__name__}"
        return f"'version' must be an int, got {shown} (expected {expected})"
    if version != expected:
        return f"format version {version}, expected {expected}"
    return None


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
        note(f"{LINKS_FILE} unreadable ({type(error).__name__}: {error}); using built-in defaults")
        return {}
    if not isinstance(links, dict):
        note(f"{LINKS_FILE} is not a JSON object; using built-in defaults")
        return {}
    # 闸门排在"是不是对象"之后：文档不是对象时，报"版本缺字段"是答非所问，上面那句才是
    # 真正的原因（同 load_tools / load_commands 的分法）。
    problem = config_version_problem(links.get("version"), LINKS_FORMAT)
    if problem:
        note(f"{LINKS_FILE}: {problem}; using built-in defaults")
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
            note(f"links.json: {slot!r} must be a module-path string, got {path!r}; using {default_module!r}")
        else:
            try:
                module = importlib.import_module(path)
                missing = [name for name in members if not hasattr(module, name)]
                if missing:
                    raise AttributeError(f"missing {', '.join(missing)}")
                return module
            except Exception as error:
                note(f"links.json: {slot!r} -> {path!r} unusable ({type(error).__name__}: {error}); using {default_module!r}")
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
        note(f"links.json: 'system_prompt_file' must be a path string, got {path!r}; using {SYSTEM_PROMPT_FILE!r}")
        path = None
    if path is None:
        path = SYSTEM_PROMPT_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeDecodeError) as error:
        note(f"system prompt file {path!r} unreadable ({type(error).__name__}: {error}); continuing without it")
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
        note(f"{PRESETS_DIR_FILE} not found; using {list(DEFAULT_PRESET_FILES)!r}")
        return list(DEFAULT_PRESET_FILES)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        note(f"{PRESETS_DIR_FILE} unreadable ({type(error).__name__}: {error}); using {list(DEFAULT_PRESET_FILES)!r}")
        return list(DEFAULT_PRESET_FILES)
    if not isinstance(config, dict):
        note(f"{PRESETS_DIR_FILE} is not a JSON object; using {list(DEFAULT_PRESET_FILES)!r}")
        return list(DEFAULT_PRESET_FILES)
    problem = config_version_problem(config.get("version"), PRESETS_DIR_FORMAT)
    if problem:
        note(f"{PRESETS_DIR_FILE}: {problem}; using {list(DEFAULT_PRESET_FILES)!r}")
        return list(DEFAULT_PRESET_FILES)
    paths = config.get("presets_dir")
    # 单个字符串按只有一项处理：手写时不必为了一个预置套一层数组。
    # 空数组是合法的"一份都不要"（下面工具层会因此不过滤），不是坏配置。
    if isinstance(paths, str) and paths:
        return [paths]
    if isinstance(paths, list) and all(isinstance(item, str) and item for item in paths):
        return paths
    note(f"{PRESETS_DIR_FILE}: 'presets_dir' must be a path or a list of paths, got {paths!r}; using {list(DEFAULT_PRESET_FILES)!r}")
    return list(DEFAULT_PRESET_FILES)


def load_tools() -> list:
    # 返回 [(模块路径, 类名), ...]，顺序＝文件里的书写顺序（dict 保序，工具给模型的顺序因此
    # 由 tools.json 决定）。只读配置，不导入任何模块：路径指错了要一行行报，那是工具层的活。
    # 降级一律返回空表：工具层的失败方向只能是"少几个工具"。文件坏了就凭空多出工具来才是灾难。
    try:
        with open(TOOLS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        note(f"{TOOLS_FILE} not found; no tools will be registered")
        return []
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        note(f"{TOOLS_FILE} unreadable ({type(error).__name__}: {error}); no tools will be registered")
        return []
    if not isinstance(config, dict):
        # 与下面 'tools' 那条分开报：顶层不是对象时 config.get 根本无从谈起，报成
        # "'tools' ... got None" 会把人往错的方向引（同 load_links 的分法）。
        note(f"{TOOLS_FILE} is not a JSON object; no tools will be registered")
        return []
    problem = config_version_problem(config.get("version"), TOOLS_FORMAT)
    if problem:
        # 立刻返回，不能落进下面的正常解析：那样同一个文件会先报版本、再报"没有可用条目"，
        # 一个坏文件吵两次。
        note(f"{TOOLS_FILE}: {problem}; no tools will be registered")
        return []
    tools = config.get("tools")
    if not isinstance(tools, dict):
        note(f"{TOOLS_FILE}: 'tools' must be an object of module-path -> class-name, got {tools!r}; no tools will be registered")
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
        note(f"{TOOLS_FILE}: skipped {bad!r} (path and class must both be non-empty strings)")
    if not entries:
        note(f"{TOOLS_FILE}: no usable tool entry; no tools will be registered")
    return entries


def load_commands() -> dict:
    # 返回 {命令名: 工具名}，顺序无所谓（查表，不是清单）。只读配置，不查工具是否真的注册：
    # 那要对着注册表才知道，留给运行时（指错了会以 tool_error 的形式打出来）。
    # 降级一律返回空表：失败方向只能是"没有指令"——文件坏了反而多出指令来才是灾难，
    # 与 load_tools 同一条理由。空表不再补一句：没有指令是合法状态（不像"一个工具都没有"）。
    try:
        with open(COMMANDS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        note(f"{COMMANDS_FILE} not found; no slash commands will be available")
        return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        note(f"{COMMANDS_FILE} unreadable ({type(error).__name__}: {error}); no slash commands will be available")
        return {}
    if not isinstance(config, dict):
        note(f"{COMMANDS_FILE} is not a JSON object; no slash commands will be available")
        return {}
    problem = config_version_problem(config.get("version"), COMMANDS_FORMAT)
    if problem:
        # 与 load_tools 同：立刻返回，别落进正常解析去多报一句。
        note(f"{COMMANDS_FILE}: {problem}; no slash commands will be available")
        return {}
    commands = config.get("commands")
    if not isinstance(commands, dict):
        note(f"{COMMANDS_FILE}: 'commands' must be an object of command -> tool-name, got {commands!r}; no slash commands will be available")
        return {}
    entries = {}
    bad = []
    for command, tool_name in commands.items():
        # 命令名必须带前导斜杠：解析出来的命令 token 是带斜杠的，不带就是永远匹配不上的死条目。
        if isinstance(command, str) and command.startswith("/") and len(command) > 1 and isinstance(tool_name, str) and tool_name:
            entries[command] = tool_name
        else:
            bad.append((command, tool_name))
    if bad:
        # 坏条目攒成一行，不是一条一行（同 load_tools 的理由）。
        note(f"{COMMANDS_FILE}: skipped {bad!r} (command must be a '/'-prefixed string and the tool name a non-empty string)")
    return entries


def to_questionary_type(choices: list, key: str) -> list:
    # dict 选项转成 questionary 认的 {"name", "value"}；字符串选项本来就认，原样留下。
    return [
        {"name": str(item[key]), "value": item} if isinstance(item, dict) else item
        for item in choices
    ]


def select(choices: list, message: str):
    # 只有 questionary 一处：转换好的选项（见 to_questionary_type）或字符串表都收。
    # 取消（Esc / Ctrl-C）返回 None，调用方要判空。
    return questionary.select(message, choices).ask()


def ask_text(message: str):
    # 与 select 同策：取消返回 None，调用方判空。
    return questionary.text(message).ask()
