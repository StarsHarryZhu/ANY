from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from src.utils import console, load_commands, load_links, load_system_prompt, note, resolve_module
from src.tools._tool_console import tool_console

import datetime

# 流式期间只渲染最近这么多字符，不能删。Live 默认 vertical_overflow="ellipsis"：
# 内容超屏时取 lines[:height-1] 补省略号，即裁底部、锁顶部，全文渲染会让长回复
# 看着像卡住。终稿不受影响，stop() 会把 overflow 切成 "visible"，始终完整。
# （版本相关：rich 的 overflow 策略照当前版本实测，升级后要重验。）
STREAM_TAIL = 4000

# 续档回放的上限：只放完整历史的最后这么多条。历史是只增不减的，一次回放几百条既没人看
# 也拖慢启动；截断的那一头本来就是最久远、最不相关的那端。
HISTORY_REPLAY = 50


def _run_stream(llm, model_name: str, instructions: str, context: list, effort: str, tools, max_output_tokens: int, display: bool = True):
    # 一轮完整的流式请求：发起 → 边收边渲染 → 终稿 →（无论如何）拆 Live、关流。返回 response。
    # 两处调用：正常对话回合，以及 compact 的摘要轮（tools 传 None，那一轮不给模型工具，
    # display 也传 False——见下）。
    #
    # display=False 是"后台轮"：照样把流读干、照样拿终稿，但一个字都不上屏。compact 的摘要
    # 走这条——那段文字是机械产物，用户要的是压缩后的用量，不是摘要本身；它作为回复也没有
    # 意义（用户没问它任何东西）。注意这跟"结果不显示"不是一回事：摘要是真的进了 context。
    #
    # 中断路径刻意不调 stream_complete：被打断的那一轮 anthropic 会给出一个 thinking 块
    # 没有配对签名的残缺消息，塞进 context 下一轮会被拒。丢掉这半轮是正确行为，别在这里
    # "顺手补个 drain"。代价是留下一条没有回复的 user 消息——安全：两家都容忍连续同角色
    # 消息（会合并），看到别当成 bug 去"修"。
    # 也正因为如此，这里不接 KeyboardInterrupt：它穿出去由最外层收，"被打断的半轮整个作废"
    # 这条语义因此只有一处实现。
    stream = llm.start_stream(model_name, instructions, context, effort, tools, max_output_tokens)

    live = None
    streamed = []

    try:
        for text in stream:
            # 后台轮：照读不误，但不建 Live、不攒文本（攒了也没人用）。流必须读完，
            # 终稿是 stream_complete 从 SDK 流内部取出来的。
            if not display:
                continue
            if live is None:
                # 懒启动：纯 tool_use 轮没有文本，不留空区域也不打印头。
                # Live 活动期间 stdout 被换成 FileProxy，不能 console.input()，
                # 连 print 也会被吞——所以工具行排在 Live 拆掉之后。每轮必须
                # 等 finally 里 stop() 完整退出再开下一个：console 上已有 Live
                # 时 set_live 返回 False，新 Live 会静默退化成 _nested，症状是
                # start() 不生效、只在 stop() 时打印一次。
                console.print("[green]Model:[/green]")
                live = Live(Text(""), console=console, refresh_per_second=8)
                live.start()
            streamed.append(text)
            live.update(Text("".join(streamed)[-STREAM_TAIL:]))

        response = llm.stream_complete(stream)

        if live is not None:
            # stop() 会把 overflow 切成 visible，终稿始终完整
            live.update(Markdown(response.output_text))
        elif display and response.output_text:
            # 兜底：provider 只给了终稿、没给增量
            console.print("[green]Model:[/green]")
            console.print(Markdown(response.output_text))
        return response
    finally:
        # 两层嵌套：任一清理抛异常都不会吃掉另一个。Ctrl-C 后光标能恢复
        # 靠的就是 live.stop() 一定执行。
        try:
            if live is not None:
                live.stop()
        finally:
            stream.close()


def _print_context_usage(used: int, window: int, approximate: bool = False) -> None:
    # 用量行的唯一写法，每轮结束和改了工作集的指令之后都走它，两处形状必须一致。
    # 别写成带反斜杠续行的 f-string：源码里的缩进会原样进字符串（这行以前就带着一长串
    # 空格，括号前面空出一大截）。
    # 两处都要用 used_context 而不是 total_tokens：后者在 Anthropic 上不含缓存读写，
    # 而缓存命中的那部分正是长会话里上下文的大头，拿它算占用率会低得离谱（实测构造样例里
    # 少报 61 倍），且越到后面错得越多。同一个量，别只改一半。
    shown = f"~{used}" if approximate else str(used)
    console.print(f"[yellow]context:[/yellow] {shown} / {window} ({used / window * 100:.1f}%)\n")


def _compacted_context_size(response) -> int:
    # 压缩后的工作集就是那条摘要消息，也就是那一轮的模型输出正文：output_tokens 里含思考
    # token，而思考没进 context，所以减掉。量不到的是系统提示词、工具定义与摘要前缀——
    # 所以调用方报它时带 ~，别把它当成整请求的用量。
    return response.output_tokens - response.reasoning_tokens


def _print_tool_call(name: str, arguments: str, result: str) -> None:
    # 工具行的唯一写法。模型自己调的工具和用户敲的指令打的是同一行，形状逐字一致
    # （续档回放里那条也是照它写的）。
    # 用 Text 而不是 f-string：arguments / result 里的方括号不该被 rich 当标记解析。
    console.print(Text.assemble(
        ("[tool] ", "dim"),
        (name, "yellow"),
        (f"({arguments})", "dim"),
        (" -> ", "dim"),
        (result, "dim"),
    ))


def _parse_command(user_input: str):
    # 斜杠指令的解析：输入以 / 开头时，/ 到第一个空白之间是命令名，其余是它的文本。
    # 返回 (命令名, 文本)；不是指令返回 (None, None)。
    # 只认"斜杠后还有非空白字符"："/" 和 "/ 内容" 的命令名是空的，不算指令，整行照旧当
    # 普通输入发出去——否则 "/" 会被包装成 user_command() 这种没有名字的东西。
    if not user_input.startswith("/"):
        return None, None
    parts = user_input.split(maxsplit=1)  # 按任意空白切，顺手吃掉多余空格
    if len(parts[0]) < 2:
        return None, None
    return parts[0], parts[1] if len(parts) > 1 else ""


# 循环层不认 provider，只认 llm_protocol：这里出现任何 if provider == ...
# 都说明该往 wrapper 加方法，而不是在调用方分叉。
#
# 渲染观感必须在真实 tty 里看：非 tty（管道、重定向、| tee）下 rich 会把渲染推迟到
# stop() 时打印一次、没有任何控制码，看着"正常"其实不是真实效果。
def control_loop(llm, models: list, system_prompt: str = None, context: list = None, provider_meta: dict = None):
    # 三个可插拔槽位（选择器 / 会话存取 / 系统提示词文件）在这里解析一次：links.json 缺失、
    # 损坏、指错都只打一行 dim 退回内置默认，绝不因配置问题崩在启动上。
    # provider_meta 是原样写进存档的不透明身份（provider 名 + API 种类），本层不解读、不
    # 比较——比较在 saver_loader.load_session 里，循环层因此没有按 provider 分叉的机会。
    links = load_links()
    # 斜杠指令表（命令名 -> 工具名）。它归本层：指令是循环层对输入的解读，"循环层不认工具表"
    # 那条规则针对的是 tools.json，这条不受影响。坏文件＝没有指令，绝不崩在启动上。
    commands = load_commands()
    choosing = resolve_module(links, "choosing_module", "src.default_choosing", ["model_choose", "reasoning_choose"])
    saver_loader = resolve_module(links, "saver_loader_module", "src.default_saver_loader", ["choose_session", "save_session", "load_session"])

    # 空模型表是配置问题：让它进到选择器里才炸的话，报出来的是 questionary 内部的
    # "A list of choices needs to be provided."，看不出根因。
    if not models:
        console.print("[red]providers.<name>.models is empty; nothing to chat with.[/red]")
        return

    # 会话在选型之前定：续档时模型和强度从档里来，两个选择器可能都不用弹。
    # 会话名对本层是不透明的把手——怎么问、存哪儿、目录怎么排都是 saver_loader 槽位的事。
    # 显式传了 context 的调用方不进会话流程：不问名字，也不落盘（对话由调用方自己管）。
    session_name = None
    state = None
    if context is None:
        session_name = saver_loader.choose_session()
        if session_name is None:
            console.print("[red]Cancelled.[/red]")
            return
        state = saver_loader.load_session(session_name, provider_meta)
    resumed_context = None
    resumed_messages = None
    # 两份都要：context 是当前发给模型的工作集（压缩过的会话里它只有一条摘要），
    # messages 是完整历史。少一份就不知道该发什么、或该回放什么，所以缺一不可。
    if isinstance(state, dict) and isinstance(state.get("context"), list) and isinstance(state.get("messages"), list):
        resumed_context = state["context"]
        resumed_messages = state["messages"]
        note(f"Resumed session {session_name!r}: {len(resumed_context)} in context, {len(resumed_messages)} in history.")

    # 档里的模型还在当前配置里、强度也还在它的选项里，才跳过选择器；否则照常选，但已载入
    # 的 context 保留——换模型不该丢掉聊过的内容。
    model = None
    effort = None
    if resumed_context is not None:
        saved_name = state.get("model")
        saved_effort = state.get("effort")
        candidate = next((item for item in models if item.get("name") == saved_name), None)
        if candidate is not None and saved_effort in (candidate.get("efforts") or []):
            model, effort = candidate, saved_effort
        elif candidate is None:
            note(f"Saved model {saved_name!r} is not in the config anymore; pick again (session kept).")
        else:
            note(f"Saved effort {saved_effort!r} is not offered by {saved_name!r}; pick again (session kept).")

    if model is None:
        model = choosing.model_choose(models)
        if model is None:
            console.print("[red]Cancelled.[/red]")
            return

        effort = choosing.reasoning_choose(model)
        if effort is None:
            console.print("[red]Cancelled.[/red]")
            return

    model_name = model["name"]
    max_context_window = model["context_window"]

    # 显式传入 system_prompt 的调用方拿到的就是它自己的字符串，外置 md 不参与。
    # 日期行保持原样；md 内容非空时才另起一行追加，空文件 ⇒ 与没有这个功能逐字一致。
    if system_prompt is None:
        system_prompt = f"You are {model_name}. Today is {datetime.datetime.now().strftime('%Y-%m-%d')}"
        extra = load_system_prompt(links)
        if extra:
            system_prompt += "\n" + extra

    console.print(Text.assemble(("Using model: ", "dim"), (model_name, "bold"), (f" (effort={effort})", "dim")))

    # 两份账从此分岔，只有 compact 会把它们拉远：
    # context 是当前发给模型的工作集，messages 是完整历史对话（只增不减）。
    # 续档时两份都从存档来；显式传 context 的调用方给的本身就是全部已知历史，复制一份当
    # 档案（浅拷贝即可：消息 dict 建好之后没人再改它）。
    if context is None:
        context = resumed_context if resumed_context is not None else []
        messages = resumed_messages if resumed_messages is not None else []
    else:
        messages = list(context)

    # complete 最近跑出来的那一轮 response。指令执行完要拿它的 token 计数报新用量——
    # 压缩后的工作集就是刚刚那段模型输出，除此之外量不到任何东西（详见指令那一段）。
    last_response = None

    def complete(instructions: str, input: list) -> str:
        # 给"需要自己跑一轮模型"的工具（当前只有 compact）递过去的窄接缝：工具层因此不
        # 认识 llm、也没 import 它，这是循环层给的一次性回调。
        # 参数名与 start_stream 对齐：instructions 是系统提示，input 是要处理的对话。
        # tools=None：摘要轮不给模型任何工具——它只该写摘要，不该顺手调个 current_time。
        # display=False：摘要不上屏。它是机械产物，用户要的是压缩后的用量，而这段文字作为
        # "回复"也没有意义（用户什么都没问）。真要看摘要本身，它在存档的 context 里。
        nonlocal last_response
        last_response = _run_stream(llm, model_name, instructions, input, effort, None, model["max_output_tokens"], display=False)
        return last_response.output_text

    tools = tool_console()

    # 续档后按当时的打印方式把历史重来一遍：User: / Model:（Markdown 终稿）/
    # [tool] 那一行，三种标记和样式都与活着那轮逐字一致；思考块不回放（当时也没上屏），
    # 每轮的用量行不在存档里（context 只存消息），所以回放里没有它。
    # 位置刻意排在所有选择器与工具预置之后：回放紧贴在输入提示之上，接着往下聊时
    # 一眼能看到聊到哪儿了。
    # 摊平是 wrapper 的事（context 里是 provider 原生块），本层只认这三种角色——
    # 这里出现按 provider 分叉的形状判断，就说明接缝破了。
    # 只有选中已有会话才有得放：显式传 context 的调用方没加载会话，历史归它自己管。
    # 放的是 messages（完整历史）的最后 HISTORY_REPLAY 条，不是 context：压缩过的会话里
    # context 只剩一条摘要，回放它等于把屏幕上已经发生过的历史擦掉。
    # 切片落在哪儿都可能切散一对 tool_use / tool_result，落单的那条由 wrapper 给成
    # result=None（下面那个 "?" 分支就是为它留的）。
    if messages:
        tail = messages[-HISTORY_REPLAY:]
        if len(tail) < len(messages):
            note(f"--- history (last {HISTORY_REPLAY} of {len(messages)} messages) ---")
        else:
            note("--- history ---")
        for row in llm.context_display(tail):
            if row["role"] == "assistant":
                console.print("[green]Model:[/green]")
                console.print(Markdown(row["text"]))
            elif row["role"] == "tool":
                # 与工具轮那行同形（Live 拆掉之后打的那条），result 为 None 说明
                # 存档里那个调用没有配对的回执（正常写不出这种档，手工改过才会有）
                console.print(Text.assemble(
                    ("[tool] ", "dim"),
                    (row["name"], "yellow"),
                    (f"({row['arguments']})", "dim"),
                    (" -> ", "dim"),
                    (row["result"] if row["result"] is not None else "?", "dim"),
                ))
            else:
                # 用 Text 而不是 f-string：用户当年敲的方括号不该被 rich 当标记解析
                console.print(Text.assemble(("User: ", "cyan"), row["text"]))

    while True:
        try:
            user_input = console.input("[cyan]User:[/cyan] ")
            if not user_input.strip():
                note("Empty input, please try again.")
                continue

            # 斜杠指令在这里落地，全程在本层：解析、查 commands.json、调 tool_run。
            # 指令也是 toolcall（走同一个 tool_run），只是发起方是用户而不是模型——
            # 所以打的是同一行 [tool]，也共用同一份实现。没有这一层的话，用户想压缩
            # 对话就得先求模型调一次工具。
            command, rest = _parse_command(user_input)
            if command is not None:
                tool_name = commands.get(command)
                if tool_name is None:
                    # 没扫到对应指令：包装成 user_command(...) 交给模型（去掉斜杠，
                    # 尾部文本原样跟在后面）。所有指令都注册成了工具，模型因此能认出
                    # 这是敲错的指令，自己调那个工具把话补完——这就是包装的全部用途。
                    user_input = f"user_command({command[1:]})" + (f" {rest}" if rest else "")
                else:
                    # 指令不带参数：commands.json 只把命令名映射到工具名，尾部文本走模型
                    # 那条路。这个字面量要喂给两处（执行与打印），提出来免得改一处漏一处。
                    arguments = "{}"
                    result = tools.tool_run(tool_name, arguments, context=context, complete=complete)
                    # 指令可能改了 context（compact 就会），改完立刻落盘：下一件事可能
                    # 是 Ctrl-C 直接退出，不能让压缩结果只活在内存里。
                    if session_name is not None:
                        saver_loader.save_session(session_name, context, messages, model_name, effort, provider_meta)
                    if rest:
                        # 带文本：指令执行过了，去掉指令，把剩下的文本当普通输入发出去。
                        # 这里一个字都不打——接下去那一轮结束时的用量行是压缩后实测的，
                        # 比这里的估计还准，两行连着打只会让人以为压了两次。
                        user_input = rest
                    else:
                        # 只有指令：本轮到此为止，不进模型回合。该打的是这次执行的结果。
                        if tool_name in tools.context_tools and last_response is not None:
                            # 换了工作集的指令（compact）不回那串 JSON——里面只有条数和旧长度，
                            # 没人要看——改报换完之后的用量。
                            _print_context_usage(_compacted_context_size(last_response), max_context_window, approximate=True)
                        else:
                            _print_tool_call(tool_name, arguments, result)
                        continue

            message = {"role": "user", "content": user_input}
            context.append(message)
            messages.append(message)

            while True:
                response = _run_stream(llm, model_name, system_prompt, context, effort, tools.tool_define(), model["max_output_tokens"])

                calls = response.tool_calls
                if not calls:
                    break

                results = []
                # 排在 Live 拆掉之后：Live 期间 stdout 是 FileProxy，打印会被吞。
                for call in calls:
                    name = response.tool_call_name(call)
                    arguments = response.tool_call_arguments(call)
                    # context / complete 只有声明了 NEEDS_CONTEXT 的工具收得到
                    # （没声明的多传会 TypeError，由 tool_run 按注册项判断）。
                    result = tools.tool_run(name, arguments, context=context, complete=complete)
                    _print_tool_call(name, arguments, result)
                    results.append(result)

                # 信封的有无由 wrapper 决定，两个 provider 都是这一行。
                # 只传 results：调用项由 wrapper 从 response.tool_calls 取。
                # 模型自己调 compact 时 context 已被换成摘要，信封照常接在它后面
                # （自带 assistant tool_use + user tool_result 一对，结构合法），
                # 模型就在压缩后的历史上继续这一轮；messages 侧一行不少。
                envelope = response.tool_continuation(results)
                context.extend(envelope)
                messages.extend(envelope)

            message = {"role": "assistant", "content": response.output_text}
            context.append(message)
            messages.append(message)

            # 回复本身已经由 Live 渲染过了，这里只剩状态行。
            _print_context_usage(response.used_context, max_context_window)

            # 每轮回复后整篇落盘：工具轮 extend 进去的部分自然包含在内，两份都写。
            # 写失败只打一行 dim（见 default_saver_loader），不打断对话。
            if session_name is not None:
                saver_loader.save_session(session_name, context, messages, model_name, effort, provider_meta)

        except (KeyboardInterrupt, EOFError):
            note("\nExiting control loop.")
            break

    # 退出前再落一次：被打断的那一轮可能留下一条没有回复的 user 消息——那是合法状态
    # （两家都容忍连续同角色，见上面的注释），存下来比丢掉强。取消选择器的路径在上面
    # 的 return 就结束了，不会走到这里，也不会碰已有存档。
    # 判空用 messages：它是只增不减的完整历史，这边非空就等于这次会话确实发生过什么。
    if session_name is not None and messages:
        try:
            saver_loader.save_session(session_name, context, messages, model_name, effort, provider_meta)
        except KeyboardInterrupt:
            # 第二次 Ctrl-C 正好落在收尾写盘上：文件不会被写坏（os.replace 是原子的），
            # 安静退出即可，别弹 traceback。
            pass
