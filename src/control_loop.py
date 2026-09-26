from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from src.utils import select, to_questionary_type, console
from src.tools.tool_console import tool_console

import datetime

# 流式期间只渲染最近这么多字符：Live 默认的 overflow 策略是裁掉底部、锁住
# 顶部，全文渲染会让长回复看着像卡住。终稿不受影响，永远完整。
STREAM_TAIL = 4000

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
                try:
                    for text in stream:
                        if live is None:
                            # 懒启动：纯 tool_use 轮没有文本，不留空区域也不打印头
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

                # 信封的有无由 wrapper 决定，两个 provider 都是这一行
                context.extend(response.tool_continuation(calls, results))


            

            context.append({"role": "assistant", "content": response.output_text})

            # 回复本身已经由 Live 渲染过了，这里只剩状态行
            console.print(f"[yellow]context:[/yellow] {response.total_tokens} / {max_context_window} \
                          ({response.total_tokens / max_context_window * 100:.1f}%)\n")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting control loop.[/dim]")
            break
