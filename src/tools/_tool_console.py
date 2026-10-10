import importlib
import json

from src.utils import TOOLS_FILE, console, load_preset_files, load_tools, select, to_questionary_type

# "全放行"哨兵：出现在清单第一位＝不过滤，全放；出现在别的位置＝跳过这一条。
# ID 0 留给它（见 _build_registry 的 ID 检查），所以这个二元组不会与任何真工具撞上，
# 光看 preset.json 也能一眼认出哪条是哨兵。
NO_RESTRICTION = ("no-restriction", 0)

def _load_tool_classes() -> list:
    # tools.json 的 (模块路径, 类名) -> 类对象。这里是全仓库唯一 import 具体工具模块的地方：
    # 模块在导入期就要拉自己的第三方依赖（timer 拉 tzlocal、location 拉 requests），
    # 所以"某个工具坏了"的全部后果都收在这一处。
    #
    # 导入失败、模块里没有这个名字、拿到的不是类对象，都按"这份清单指错了"处理：打一行 dim
    # 跳过它，不拖垮启动（与 links.json 的槽位解析同一套降级）。跳过也只可能让工具变少，
    # 不会凭空多出来。拿到的确实是类、但类本身违了工具契约（ID 非法、get_method() 缺键、
    # 与别的工具撞名撞 ID），那是写工具的人的代码 bug，交给 _build_registry 抛。
    classes = []
    failures = []
    for module_path, class_name in load_tools():
        try:
            module = importlib.import_module(module_path)
            tool_class = getattr(module, class_name)
            if not isinstance(tool_class, type):
                raise TypeError(f"{class_name!r} is not a class")
        except Exception as error:
            failures.append(f"{module_path}.{class_name} ({type(error).__name__}: {error})")
            continue
        # 同一个类在清单里写了两遍：注册一遍就够，静默去重——这份清单描述的工具集没有变化，
        # 没有需要用户处理的东西（两条不同的类撞名撞 ID 才是要吵的事）。
        if tool_class in classes:
            continue
        classes.append(tool_class)
    if failures:
        # 一行说完：坏文件只该吵一次（同 load_links 的理由）。一条都没成时把后果也带上——
        # 清单读不出来（文件缺失/坏掉/空表）那几种情况 load_tools 已经报过原因，这里不再补一句，
        # 否则同一件事会连着打两行。
        tail = " (no tool loaded)" if not classes else ""
        console.print(f"[dim]{TOOLS_FILE}: skipped {', '.join(failures)}{tail}[/dim]")
    return classes


def _build_registry(classes: list) -> list:
    # 这里抛的都是仓库自己的代码错了——get_method() 缺键、parameters 形状不对、ID 非法、
    # 名字或 ID 重复——按约定直接抛，不走"打一行 dim 退回默认"：那是配置问题的待遇。
    registry = []
    by_id = {}
    for cls in classes:
        instance = cls()
        for member in ("get_method", "toolcall"):
            # 清单指到一个真实存在、但不是工具的类（collections.OrderedDict 这种）会走到这里。
            # 不检查的话下面是一句裸 AttributeError，看不出是哪个类、也看不出是配置指错了。
            if not callable(getattr(instance, member, None)):
                raise ValueError(f"tool class {cls.__name__}: no {member}(); a tool class needs get_method() and toolcall()")
        method = instance.get_method()
        for key in ("name", "id", "description", "parameters"):
            if key not in method:
                # 顺手把 description 拼成 discription 这类错挡在启动期：拖到 wrapper 构造请求
                # 时才炸的话，报出来的是 KeyError，看不出是哪个工具。
                raise ValueError(f"tool class {cls.__name__}: get_method() is missing {key!r}")
        name, tool_id = method["name"], method["id"]
        if not isinstance(method["parameters"], dict):
            raise ValueError(f"tool {name!r}: parameters must be a JSON-Schema object, got {type(method['parameters']).__name__}")
        if name == NO_RESTRICTION[0]:
            raise ValueError(f"tool name {name!r} is reserved for the no-restriction sentinel")
        # bool 是 int 的子类：不挡的话 ID = True 会悄悄变成 ID 1。
        if isinstance(tool_id, bool) or not isinstance(tool_id, int) or tool_id <= 0:
            raise ValueError(f"tool {name!r}: id must be a positive int, got {tool_id!r} (0 is reserved for the {NO_RESTRICTION[0]!r} sentinel)")
        if any(item["name"] == name for item in registry):
            # impls 按 name 索引，重名会静默覆盖：必须在建表期就炸
            raise ValueError(f"duplicate tool name {name!r}")
        if tool_id in by_id:
            # 名字已经唯一，(name, id) 这个二元组因此也唯一；ID 再单独查一遍，是因为它是
            # preset.json 里的选择键，一个不唯一的 ID 不配当身份。
            raise ValueError(f"tool id {tool_id:#x} is already used by {by_id[tool_id]!r}")
        by_id[tool_id] = name
        registry.append({
            "name": name,
            "id": tool_id,
            "description": method["description"],
            "parameters": method["parameters"],
            "impl": instance.toolcall,
        })
    return registry


def _entry_id(value):
    # 清单里的 ID 字面量 -> int；不合法返回 None。
    # JSON 没有十六进制字面量，文件里只能写十进制；为了让手写时能照抄 Python 那边的 0x02，
    # 字符串形式也收。字符串走 int(s, 0)（认 0x 前缀，也认十进制）——不能用 int(s, 16)，
    # 它会把 "10" 读成 16。
    if isinstance(value, bool):  # 不先挡，JSON 的 true 会变成 ID 1
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def _is_sentinel(entry) -> bool:
    # JSON 解出来的是 list，常量是 tuple，直接 == 永远不相等，所以两边都归一后再比。
    return (
        isinstance(entry, (list, tuple))
        and len(entry) == 2
        and entry[0] == NO_RESTRICTION[0]
        and _entry_id(entry[1]) == NO_RESTRICTION[1]
    )


def _load_presets() -> list:
    # presets_dir.json 给出路径表，逐个读成 {"path", "label", "entries"}。
    # 读不出来的整份跳过（文件不在、解不开、顶层不是对象、tools 不是数组），失败理由攒成
    # 一行 dim：坏文件只该吵一次，不是一份一行（同 load_links 的理由）。
    # 条目本身的好坏不在这里判：那要对着注册表才知道谁匹配得上，留给 _select_tools。
    presets = []
    failures = []
    seen = set()
    for path in load_preset_files():
        if path in seen:  # 同一份列了两遍：只提供一次
            continue
        seen.add(path)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                document = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(f"{path!r} ({type(error).__name__}: {error})")
            continue
        # 顶层必须是对象：preset_name 和 tools 两个字段都在里面。
        entries = document.get("tools") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            failures.append(f"{path!r} (no 'tools' list)")
            continue
        label = document.get("preset_name")
        if not isinstance(label, str) or not label:
            # 显示名只是装饰：缺了退回显示路径，清单照常执行——不能因为一个标签让整份预置失效，
            # 更不能因此放开全部工具。
            console.print(f"[dim]preset {path!r}: no 'preset_name'; showing the path instead[/dim]")
            label = path
        presets.append({"path": path, "label": label, "entries": entries})
    if failures:
        console.print(f"[dim]preset(s) skipped: {'; '.join(failures)}[/dim]")
    if not presets:
        console.print("[dim]no usable preset; loading all tools[/dim]")
    return presets


def _choose_preset(presets: list):
    # 启动时的预置选择器。返回选中的那份（dict），None 表示不过滤（全放行）。
    #
    # 这是全仓库唯一一个不在 default_choosing.py 里的选择器：它选的是工具层的东西，而
    # control_loop 不认工具（src/AGENTS.md 那条规则针对的是循环层）。要挪进 choosing_module
    # 槽位，得先给槽位的 members 加成员，那会让所有自定义选择器模块因为缺这个成员而整套退回
    # 默认，代价比一个函数大得多。
    if not presets:
        # 不弹空选择器：questionary 拿到空列表会在库内部抛
        # ValueError("A list of choices needs to be provided.")，报错看不出根因
        # （同 reasoning_choose 的处理）。
        return None
    # 两步走：先用 to_questionary_type 转成 questionary 认的形状，再 select
    # （与 default_choosing 一致）。取消时 select 返回 None。
    picked = select(to_questionary_type(presets, "label"), "Select tool preset")
    if picked is None:
        # 取消不退出：这里不是模型选择器那种"取消＝不想聊"的承诺点，工具只是可选层，退回默认
        # （全放行）继续跑，只报一行。也不能抛 KeyboardInterrupt：tool_console 在 control_loop
        # 的 try 之外构造，抛出去只会带 traceback 崩掉整个启动。
        console.print("[dim]tool preset selection cancelled; loading all tools[/dim]")
        return None
    return picked


def _select_tools(registry: list, preset) -> list:
    # 按预置清单过滤注册表。preset 为 None ＝不过滤（没配置 / 一份都没读出来 / 用户取消）。
    if preset is None:
        return registry
    entries = preset["entries"]
    if entries and _is_sentinel(entries[0]):
        # 哨兵在第一位＝全放行，后面的条目按约定不再看。
        return registry
    notes = []
    wanted = set()
    for position, entry in enumerate(entries):
        tool_id = _entry_id(entry[1]) if isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str) else None
        if tool_id is None:
            notes.append(f"entry {position} malformed: {entry!r}")
            continue
        name = entry[0]
        if _is_sentinel(entry):
            # 哨兵只在第一位有效：出现在别处＝位置写错了，跳过这条，继续看后面的。
            notes.append(f"ignored {name!r} at position {position} (only the first entry may be it)")
            continue
        match = next((item for item in registry if item["name"] == name and item["id"] == tool_id), None)
        if match is None:
            notes.append(f"no tool matches {(name, tool_id)!r}")
            continue
        wanted.add(name)  # 集合语义：同一个工具列了两遍也只算一次，不算错
    # 顺序永远按注册表（＝ tools.json 的书写顺序）：预置只决定"哪些在"，不决定"什么顺序"。
    # 一份清单是过滤器，顺手把顺序重排了才是意外。
    selected = [item for item in registry if item["name"] in wanted]
    if notes:
        console.print(f"[dim]preset {preset['path']!r}: {'; '.join(notes)}[/dim]")
    if not selected:
        # 清单非空却一条都没选中：预置的用途是收紧，失败方向必须是收紧那侧——名字写错的后果
        # 是这轮没有工具（上面已点名），绝不能静默放开全部。
        # 顺带这也是"全程无工具"唯一的可见提示：空 tools 会被 wrapper 的 if tools: 静默丢掉。
        console.print("[dim]preset selects no tools; the model runs without any tools[/dim]")
    return selected


class tool_console():
    def __init__(self):
        # 工具层的唯一入口，两步：建注册表（仓库代码错了就在这里抛），再按预置清单过滤。
        # 构造期会弹一次预置选择器。循环层是在选完会话 / 模型 / 强度之后才构造它，所以顺序是
        # 会话 → 模型 → 强度 → 工具预置，然后才进第一轮对话；也就是说这个构造函数会阻塞在一个
        # questionary 提示上，非交互场景（管道、脚本）里 import 后 new 一个要留意。
        chosen = _select_tools(_build_registry(_load_tool_classes()), _choose_preset(_load_presets()))
        # impls 的键与 tools 里的 name 同源（都取自注册项），"两处对不上"从结构上没了。
        self.impls = {item["name"]: item["impl"] for item in chosen}
        self.tools = [
            {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["parameters"],
            }
            for item in chosen
        ]


    def tool_define(self):
        # 中立形状（name / description / parameters），与 provider 无关。
        # 两家线上形状的差异（Anthropic 的 input_schema、OpenAI 的
        # {"type": "function"} 外层）由 wrapper 的 tool_definitions() 抹平，
        # 这里不要按 provider 分叉。
        # 这是本文件最容易踩的坑：注册表若存 Anthropic 形状（input_schema），
        # wrapper 转换时 tool["parameters"] 直接 KeyError；若存 OpenAI 形状，
        # Anthropic 侧凑巧还能跑（键名正好对上，多出的 type 被忽略）——别依赖这个巧合。
        # 返回非空列表才让 wrapper 真的带上 tools 字段（_params 里是 if tools:）——
        # 注册表被清空会静默把工具从请求体里拿掉，不报错。空表由此多了一个来路：预置清单
        # 显式不要任何工具（_select_tools 会为这种情况打一行 dim，不至于让人以为是 bug）。
        return self.tools


    def tool_run(self, name: str, arguments: str) -> str:
        try:
            # arguments 是 JSON 字符串而非 dict，wrapper 的 tool_call_arguments()
            # 已统一过，直接 loads
            return json.dumps(self.impls[name](**json.loads(arguments)), ensure_ascii=False)
        except Exception as error:
            # 捕获的是 Exception：名字对不上（KeyError）、参数不是合法 JSON
            # （JSONDecodeError）、实现签名不匹配（TypeError）、工具自己抛的异常，都汇到这里。
            # 本来都会冒到循环层，而那边只捕获 KeyboardInterrupt / EOFError，会带 traceback
            # 崩掉整个 REPL。转成错误文本回给模型，让它自己看着纠正。
            # 刻意没接 BaseException：KeyboardInterrupt / SystemExit 照旧穿出去，
            # 让 Ctrl-C 仍然受控。
            #
            # tool_error 是带外标志，不是给模型看的（"error" 那个键模型就够读了）：
            # 光靠 "error"，本函数的失败输出和一个恰好返回 {"error": ...} 的工具
            # 结果完全同形，客户端分不出来。所以失败路径额外打一个标志，成功路径
            # 不打——"没有这个键"就是成功。
            # 它是本仓库的保留键，impls 的返回值里不许用。将来要把它提升成
            # Anthropic 的 is_error 字段，靠的就是这个键，tool_run 签名无需再动。
            return json.dumps(
                {"tool_error": True, "error": f"{type(error).__name__}: {error}"},
                ensure_ascii=False,
            )
