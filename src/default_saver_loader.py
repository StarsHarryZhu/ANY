import json
import os

from src.utils import ask_text, console, select

# 会话存档目录：仓库根下的 sessions/，一个会话一个文件，名字由用户取。
# 与 api_keys.json 同一约定——相对当前工作目录写死，只从仓库根运行才对。
# 目录/文件名都是本槽位的实现细节，刻意不进 links.json：换成 sqlite / 远端存储是另一个
# saver_loader 的事，循环层只拿一个不透明的会话名。
SESSIONS_DIR = "sessions"
SESSION_SUFFIX = ".json"

# 存档格式版本。context 之外的字段含义一改就 +1；版本对不上＝不加载（旧文件留成 .bak），
# 将来升级格式时旧代码不会把不认识的新字段当成有效数据用。
SESSION_FORMAT = 1

# 选择器里"新建会话"那一项的哨兵值。用 object() 而不是某个字符串：任何字符串都可能是
# 合法的会话名，哨兵必须不可能与真名字撞上（questionary 的 value 可以是任意对象）。
NEW_SESSION = object()


def _session_path(name: str) -> str:
    return os.path.join(SESSIONS_DIR, name + SESSION_SUFFIX)


def _name_problem(name: str):
    # 宽松校验：只拦真正危险的（能跑出 sessions/ 目录的、空名、控制字符），中文、空格、
    # 符号都放行。返回 None 表示合法，否则返回给用户看的原因。
    if not name:
        return "empty"
    if "/" in name or "\\" in name:
        return "must not contain a path separator"
    if name in (".", ".."):
        return "reserved name"
    if any(ord(char) < 32 for char in name):
        return "must not contain control characters"
    if len(name) > 100:
        return "too long (max 100 characters)"
    return None


def _list_sessions() -> list:
    # 会话名 = sessions/ 下 *.json 的文件名去掉后缀；.bak / .tmp 因此天然不匹配。
    # 目录不存在（全新克隆）返回空表。按 mtime 倒序：最近聊过的排最前，也就是选择器默认
    # 停在的那一项。
    try:
        entries = os.listdir(SESSIONS_DIR)
    except OSError:
        return []
    paths = [
        os.path.join(SESSIONS_DIR, entry)
        for entry in entries
        if entry.endswith(SESSION_SUFFIX) and os.path.isfile(os.path.join(SESSIONS_DIR, entry))
    ]
    try:
        paths.sort(key=os.path.getmtime, reverse=True)
    except OSError:
        paths.sort()  # 排序途中文件被删：不值得为顺序报错，退回按名字排
    return [os.path.basename(path)[: -len(SESSION_SUFFIX)] for path in paths]


def choose_session():
    # 返回会话名，用户取消返回 None。
    # 已有会话按最近改动倒序列出，最后一项是"New session…"；一个都没有时不弹选择器
    # （questionary 拿到空列表会在库内部抛 ValueError），直接问名字。
    # 新名字与已有会话重名不多问：load_session 会把它当成那个会话续上。
    names = _list_sessions()
    if names:
        choices = [{"name": name, "value": name} for name in names]
        choices.append({"name": "New session…", "value": NEW_SESSION})
        picked = select(choices, "Select session")
        if picked is None:
            return None
        if picked is not NEW_SESSION:
            return picked

    while True:
        name = ask_text("Session name:")
        if name is None:
            return None
        name = name.strip()  # 顺手去掉手滑的空格，而不是判它非法
        problem = _name_problem(name)
        if problem:
            console.print(f"[red]Invalid session name: {problem}.[/red]")
            continue
        console.print(f"[dim]New session -> {_session_path(name)}[/dim]")
        return name


def _jsonable(obj):
    # json.dump 的 default 钩子。context 里混着裸 SDK 对象：工具轮之后 tool_continuation
    # 塞进来的是 SDK 的 pydantic 块（Anthropic 的 content 块、OpenAI 的 output item），
    # 直接 dump 会 TypeError。
    # model_dump(mode="json") 把它们变回请求体原生形状的 dict——thinking 块的 signature
    # 因此原样保住，这是 Anthropic 侧下一轮能接受这段历史的唯一前提。
    # exclude_none=True 去掉 SDK 自己补的 None 字段（如 TextBlock.citations），回传时更
    # 接近原本的请求体形状。
    # 非 pydantic 对象照旧抛 TypeError：那说明 context 里被塞了不该塞的东西，是真 bug，
    # 不在这里吞——save_session 会把它连同类型打成一行 dim。
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump(mode="json", exclude_none=True)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_session(name: str, context: list, model: str, effort: str, provider_meta: dict = None) -> None:
    # 整篇重写。失败只打一行 dim 就返回：写不进盘不该弄死对话（先例：tool_run 把内部
    # 失败转成可见输出，不往上抛）。
    provider_meta = provider_meta or {}
    document = {
        "version": SESSION_FORMAT,
        "provider": provider_meta.get("provider"),
        "API": provider_meta.get("API"),
        "model": model,
        "effort": effort,
        "context": context,
    }
    path = _session_path(name)
    # 先写同目录临时文件再 os.replace：同一文件系统内 replace 是原子的，Ctrl-C 落在写盘
    # 中间最多留下半截 .tmp，正式文件永远是上一个完整版本。
    # 同一个会话并跑两个实例会抢同一个 .tmp，最坏结果是其中一次保存打一行 dim，文件不会坏。
    tmp = path + ".tmp"
    try:
        # 目录在第一次保存时才建：全新克隆里没有 sessions/，而只读配置不该产生副作用。
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(document, f, ensure_ascii=False, default=_jsonable)
        os.replace(tmp, path)
    except Exception as error:
        # 捕 Exception 而不是只捕 OSError：context 里进了不可序列化的对象时，失败点在一轮
        # 结束处，不能让它把整个 REPL 带崩。刻意不接 BaseException：KeyboardInterrupt /
        # SystemExit 照旧穿出去，Ctrl-C 仍然受控。
        console.print(f"[dim]session save failed ({type(error).__name__}: {error})[/dim]")


def _discard(path: str, reason: str):
    # 能解析但不能用的存档：改名 .bak 留底后全新开始。必须留底——自动保存每轮都跑，
    # 不备份的话第一次保存就把用户的旧会话覆盖没了。.bak 已存在会被这次改名覆盖，
    # 只保留最近一份。
    console.print(f"[dim]session not resumed ({reason}); starting fresh, old file kept as {path}.bak[/dim]")
    try:
        os.replace(path, path + ".bak")
    except OSError as error:
        console.print(f"[dim]session backup failed ({type(error).__name__}: {error})[/dim]")
    return None


def load_session(name: str, provider_meta: dict = None):
    # 返回含 version / provider / API / model / effort / context 的 dict，或 None。
    # 返回 None 且静默的唯一来源是"这个会话还没有文件"（新建会话的正常状态）；其余每种
    # 都打一行 dim。
    path = _session_path(name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            document = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        # 纯解析失败不留 .bak：没有值得保全的内容，下一次保存直接覆盖。
        console.print(f"[dim]session {name!r} unreadable ({type(error).__name__}: {error}); starting fresh[/dim]")
        return None

    if not isinstance(document, dict):
        return _discard(path, "not a JSON object")
    if document.get("version") != SESSION_FORMAT:
        return _discard(path, f"format version {document.get('version')!r}, expected {SESSION_FORMAT}")
    if not isinstance(document.get("context"), list):
        return _discard(path, "no context list")

    # provider 身份只在这里比较：循环层把 provider_meta 原样搬进来、不解读，循环层因此
    # 没有按 provider 分叉的机会。
    # API 种类不同＝context 的信封形状根本不兼容（messages 的 role 消息 vs responses 的
    # 裸 item），加载下去必然在下一次请求被端点拒收，所以放弃并留 .bak。
    # 只是 provider 名变了：形状兼容，提醒一句仍然续上——改个配置名不该毁掉整段会话，
    # 签名能不能过由端点决定。
    # 字段缺失（旧档、或编程调用没传 provider_meta）跳过检查：没有证据不等于不兼容。
    if provider_meta:
        saved_api, current_api = document.get("API"), provider_meta.get("API")
        if saved_api and current_api and saved_api != current_api:
            return _discard(path, f"saved under API {saved_api!r}, now running {current_api!r}")
        saved_provider, current_provider = document.get("provider"), provider_meta.get("provider")
        if saved_provider and current_provider and saved_provider != current_provider:
            console.print(f"[dim]note: session was saved under provider {saved_provider!r}, now {current_provider!r}; thinking signatures may be rejected[/dim]")

    return document
