from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from src.utils import console, load_links, load_system_prompt, resolve_module
from src.tools._tool_console import tool_console

import datetime

# 流式期间只渲染最近这么多字符，不能删。Live 默认 vertical_overflow="ellipsis"：
# 内容超屏时取 lines[:height-1] 补省略号，即裁底部、锁顶部，全文渲染会让长回复
# 看着像卡住。终稿不受影响，stop() 会把 overflow 切成 "visible"，始终完整。
# （版本相关：rich 的 overflow 策略照当前版本实测，升级后要重验。）
STREAM_TAIL = 4000

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
    if isinstance(state, dict) and isinstance(state.get("context"), list):
        resumed_context = state["context"]
        console.print(f"[dim]Resumed session {session_name!r}: {len(resumed_context)} messages.[/dim]")

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
            console.print(f"[dim]Saved model {saved_name!r} is not in the config anymore; pick again (session kept).[/dim]")
        else:
            console.print(f"[dim]Saved effort {saved_effort!r} is not offered by {saved_name!r}; pick again (session kept).[/dim]")

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

    console.print(f"[dim]Using model:[/dim] [bold]{model_name}[/bold] [dim](effort={effort})[/dim]")

    if context is None:
        context = resumed_context if resumed_context is not None else []

    tools = tool_console()

    # 续档后把历史重新打一遍。位置刻意排在所有选择器与工具预置之后：回放紧贴在输入
    # 提示之上，接着往下聊时一眼能看到聊到哪儿了。
    # 摊平是 wrapper 的事（context 里是 provider 原生块），本层只认 user / assistant
    # 两种角色——这里出现按 provider 分叉的形状判断，就说明接缝破了。
    # 只有选中已有会话才有得放：显式传 context 的调用方没加载会话，历史归它自己管。
    if resumed_context:
        console.print("[dim]--- history ---[/dim]")
        for row in llm.context_display(resumed_context):
            if row["role"] == "assistant":
                console.print("[green]Model:[/green]")
                console.print(Markdown(row["text"]))
            else:
                # 用 Text 而不是 f-string：用户当年敲的方括号不该被 rich 当标记解析
                console.print(Text.assemble(("User: ", "cyan"), row["text"]))

    while True:
        try:
            user_input = console.input("[cyan]User:[/cyan] ")

            context.append({"role": "user", "content": user_input})

            while True:
                stream = llm.start_stream(model_name, system_prompt, context, effort, tools.tool_define(), max_output_tokens = model["max_output_tokens"])

                live = None
                streamed = []

                # 中断路径刻意不调 stream_complete：被打断的那一轮 anthropic 会给出
                # 一个 thinking 块没有配对签名的残缺消息，塞进 context 下一轮会被拒。
                # 丢掉这半轮是正确行为，别在这里"顺手补个 drain"。
                # 代价是留下一条没有回复的 user 消息——安全：两家都容忍连续同角色
                # 消息（会合并），看到别当成 bug 去"修"。
                try:
                    for text in stream:
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
                    elif response.output_text:
                        # 兜底：provider 只给了终稿、没给增量
                        console.print("[green]Model:[/green]")
                        console.print(Markdown(response.output_text))
                finally:
                    # 两层嵌套：任一清理抛异常都不会吃掉另一个。Ctrl-C 后光标能恢复
                    # 靠的就是 live.stop() 一定执行。
                    try:
                        if live is not None:
                            live.stop()
                    finally:
                        stream.close()

                calls = response.tool_calls
                if not calls:
                    break

                results = []
                # 排在 Live 拆掉之后：Live 期间 stdout 是 FileProxy，打印会被吞。
                for call in calls:
                    name = response.tool_call_name(call)
                    arguments = response.tool_call_arguments(call)
                    result = tools.tool_run(name, arguments)
                    console.print(Text.assemble(
                        ("[tool] ", "dim"),
                        (name, "yellow"),
                        (f"({arguments})", "dim"),
                        (" -> ", "dim"),
                        (result, "dim"),
                    ))
                    results.append(result)

                # 信封的有无由 wrapper 决定，两个 provider 都是这一行。
                # 只传 results：调用项由 wrapper 从 response.tool_calls 取。
                context.extend(response.tool_continuation(results))


            

            context.append({"role": "assistant", "content": response.output_text})

            # 回复本身已经由 Live 渲染过了，这里只剩状态行。
            # 两处都要用 used_context 而不是 total_tokens：后者在 Anthropic 上
            # 不含缓存读写，而缓存命中的那部分正是长会话里上下文的大头，拿它
            # 算占用率会低得离谱（实测构造样例里少报 61 倍），且越到后面错得越多。
            # 同一个量，别只改一半。
            console.print(f"[yellow]context:[/yellow] {response.used_context} / {max_context_window} \
                          ({response.used_context / max_context_window * 100:.1f}%)\n")

            # 每轮回复后整篇落盘：工具轮 extend 进 context 的部分自然包含在内。
            # 写失败只打一行 dim（见 default_saver_loader），不打断对话。
            if session_name is not None:
                saver_loader.save_session(session_name, context, model_name, effort, provider_meta)

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting control loop.[/dim]")
            break

    # 退出前再落一次：被打断的那一轮可能留下一条没有回复的 user 消息——那是合法状态
    # （两家都容忍连续同角色，见上面的注释），存下来比丢掉强。取消选择器的路径在上面
    # 的 return 就结束了，不会走到这里，也不会碰已有存档。
    if session_name is not None and context:
        try:
            saver_loader.save_session(session_name, context, model_name, effort, provider_meta)
        except KeyboardInterrupt:
            # 第二次 Ctrl-C 正好落在收尾写盘上：文件不会被写坏（os.replace 是原子的），
            # 安静退出即可，别弹 traceback。
            pass
