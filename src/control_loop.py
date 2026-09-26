from rich.markdown import Markdown
from rich.text import Text

from src.utils import select, to_questionary_type, console
from src.tools.tool_console import tool_console

import datetime

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
                response = llm.get_response(model_name, system_prompt, context, effort, tools.tool_define())

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

            console.print("[green]Model:[/green]")
            console.print(Markdown(response.output_text))
            console.print(f"[yellow]context:[/yellow] {response.total_tokens} / {max_context_window} \
                          ({response.total_tokens / max_context_window * 100:.1f}%)\n")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Exiting control loop.[/dim]")
            break
