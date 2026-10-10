from src.utils import console, select, to_questionary_type

# 默认的模型 / 推理强度选择器：原来写在 control_loop.py 里的 questionary 单选，搬到这个
# 槽位实现里。取消（Esc / Ctrl-C）时 questionary 返回 None，控制循环据此打印 Cancelled
# 并退出——两个函数返回 None 一律表示"没有选择"。
# 要换实现（比如自动选某个模型、从环境变量取）：新写一个模块导出同名函数，再把仓库根
# links.json 的 choosing_module 指向它即可，control_loop 不需要改。


def model_choose(models: list):
    # 返回 models 里的一项（dict），取消返回 None。
    return select(to_questionary_type(models, "name"), "Select model")


def reasoning_choose(model: dict):
    # 返回选中的 effort 字符串，取消返回 None。
    # efforts 为空是配置问题：questionary 拿到空列表会在库内部抛
    # ValueError("A list of choices needs to be provided.")，从报错看不出根因，
    # 所以提前按"取消"处理，让调用方走正常的退出路径。
    efforts = model.get("efforts") or []
    if not efforts:
        console.print(f"[red]Model {model.get('name')!r} has no efforts configured.[/red]")
        return None
    return select(to_questionary_type(efforts, None), "Select reasoning effort")
