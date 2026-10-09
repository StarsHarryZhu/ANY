from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from src.utils import select, to_questionary_type, console
from src.tools.tool_console import tool_console

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
def control_loop(llm, models: list, system_prompt: str = None, context: list = None):

    model = select(to_questionary_type(models, "name"), "Select model")

    if model is None:
        console.print("[red]Cancelled.[/red]")
        return

    model_name = model["name"]
    max_context_window = model["context_window"]

    effort = select(to_questionary_type(model["efforts"], None), "Select reasoning effort")
    if effort is None:
        console.print("[red]Cancelled.[/red]")
        return

    if system_prompt is None:
        system_prompt = f"You are {model_name}. Today is {datetime.datetime.now().strftime('%Y-%m-%d')}"

    console.print(f"[dim]Using model:[/dim] [bold]{model_name}[/bold] [dim](effort={effort})[/dim]")

    if context is None:
        context = []

    tools = tool_console()

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

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting control loop.[/dim]")
            break
